"""Score the coach on judging a concrete move, and time it while doing so.

One run answers both questions the move-evaluation work has to justify itself
against: *did the coach get it right* and *did it get slower*. They share the same
live calls, so measuring them together costs one run instead of two and removes
the risk of comparing an accuracy run against a latency run taken under different
machine load.

The dataset (``book_moves.json``) is deliberately balanced between moves that are
sound and moves that lose material, phrased identically, so the accuracy figure
cannot be won by a coach that simply distrusts every move a student proposes —
the 50% line is the "always say no" baseline, not zero.

Grading is deterministic and refuses to guess: a reply that does not clearly land
on a verdict is counted as ``unclear`` rather than silently scored, because a
coach that answers ambiguously has in fact failed the student and the number
should say so instead of being rounded in its favour.

    uv run --extra evals python -m evals.tools.run_move_eval --out baseline.json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import anyio

from chess_coach.adapters.coach.agent import AgentCoach
from chess_coach.adapters.coach.analysis import MemoizingAnalyzer, StockfishAnalyzer
from chess_coach.adapters.observability import latency

GOLDENS = Path(__file__).resolve().parents[1] / "data" / "move_eval" / "book_moves.json"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"

# Phrases that commit the reply to a verdict. Matching is on whole words so that
# "not a mistake" cannot be scored as "mistake" by a bare substring hit.
# Deliberately phrase-shaped rather than word-shaped. A bare "excellent" or "solid"
# matches praise of anything in the reply — including the opponent's position — so
# every marker here has to carry its own subject to fire.
_NEGATIVE = (
    r"blunder", r"mistake", r"inaccuracy", r"\blos(?:e|es|ing)\b",
    r"drops? (?:a|the)", r"bad move", r"not (?:a )?good", r"not the best",
    r"too slow", r"refuted", r"punished", r"i'?d avoid", r"don'?t play",
    r"wouldn'?t play", r"throws? away", r"gives? up (?:a|the|material)",
    r"tempting (?:but|trap)", r"a trap", r"backfires", r"premature",
)
_POSITIVE = (
    r"good move", r"strong move", r"best move", r"is (?:actually )?(?:the )?best",
    r"perfectly (?:fine|good|playable|reasonable|sound)", r"is fine", r"is good",
    r"is strong", r"playable", r"nothing wrong with", r"is (?:a )?sound",
    r"sound move", r"excellent (?:move|choice|instinct|idea)", r"engine agrees",
    r"the engine'?s (?:top |first )?choice", r"well spotted", r"well played",
    r"solid (?:move|choice)", r"yes[,.] ?that'?s", r"right to play",
)

# "It gives up a tiny amount" and "it loses only a hair" are *endorsements* — the
# coach quantifying how little the move costs. Read as bare negatives they cancel
# the surrounding praise and turn a correct answer into "unclear", which is how two
# plainly-approving replies were scored as failures. These spans are removed before
# the negative vote is counted.
#
# Note this corrects a measurement error, not a score: both replies read as
# approval to any human. The coach must never be tuned to avoid the words the
# grader mishandles — that would be fitting the metric instead of the task.
_MINIMISED = re.compile(
    r"\b(?:los(?:e|es|ing)|gives?\s+up|drops?|costs?|concedes?)\s+"
    r"(?:only\s+)?(?:a\s+|the\s+)?"
    r"(?:tiny|very\s+little|little|small|slight(?:ly)?|bit|fraction|hair|"
    r"quarter|touch|shade)\b",
    re.IGNORECASE,
)

_NEG_RE = re.compile("|".join(_NEGATIVE), re.IGNORECASE)
_POS_RE = re.compile("|".join(_POSITIVE), re.IGNORECASE)

# A good coach condemns the student's move and then recommends a better one, so a
# reply about a *blunder* is full of praise — for a different move. Sentences that
# introduce an alternative are therefore excluded from the vote; counting them is
# how a correct "Bxf7+ is a blunder, play d4 instead" gets misread as approval.
_ALTERNATIVE = re.compile(
    r"\b(instead|rather than|engine (?:suggests|recommends|prefers|wants|likes)|"
    r"best move|better (?:is|would|move)|other (?:\w+ )?moves|"
    r"(?:try|consider|play|look at) \*{0,2}[A-Z]?[a-h]?x?[a-h][1-8]|"
    r"what should you (?:look for |play )?instead)\b",
    re.IGNORECASE,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class Outcome:
    """How the coach did on one problem, and how long it took."""

    id: str
    expected_sound: bool
    verdict: str  # sound | bad | unclear
    correct: bool
    cp_loss: int
    latency_ms: float
    reply_chars: int
    # Kept so a grader change can be re-scored offline instead of paying for
    # another live run — and so a disputed score can be read back and checked.
    move_san: str = ""
    reply: str = ""
    # The reason axis: the engine's answer to the student's move, and whether the
    # coach actually named it. A right verdict with no reason is a grade, not a lesson.
    expected_reply: str = ""
    named_reply: bool = False


def names_move(reply: str, move_san: str) -> bool:
    """Whether the coach's prose actually names ``move_san``.

    Compared without its check/mate suffix, since a coach may write ``Kxf7`` where
    the engine wrote ``Kxf7+`` (or add a ``!``), and bounded so that ``Nd5`` does not
    count as a mention of ``Nxd5`` — the two are different moves and crediting one
    for the other would inflate the score.
    """
    if not move_san:
        return False
    bare = re.escape(move_san.rstrip("+#!?"))
    return re.search(rf"(?<![\w=]){bare}(?![\w=])", reply) is not None


def _mentions(sentence: str, move_san: str | None) -> bool:
    """Whether a sentence names the student's move (markdown emphasis tolerated)."""
    if not move_san:
        return False
    bare = re.escape(move_san.rstrip("+#"))
    return re.search(rf"\*{{0,2}}{bare}[+#]?\*{{0,2}}", sentence) is not None


def classify(reply: str, move_san: str | None = None) -> str:
    """Read a prose reply as ``sound``, ``bad`` or ``unclear`` *about the student's move*.

    The verdict has to be attributed, not merely detected. A correct reply to a bad
    move condemns it and then praises the alternative, so counting sentiment across
    the whole reply reads approval where there is none. The vote therefore runs over
    the sentences that name the student's move, with sentences introducing an
    alternative excluded; only when no sentence names the move does it fall back to
    the reply as a whole.

    Both families often appear in one sentence ("it looks natural, but it drops a
    pawn"), so the side the sentence commits to more often wins, and a tie is
    reported as ``unclear`` rather than broken by a coin flip.
    """
    sentences = [s for s in _SENTENCE.split(reply) if s.strip()]
    # Narrowest scope first, widening only when the narrower one does not commit.
    # Sentences naming the move outrank the alternatives filter: "Nxd4 is the best
    # move" is praise *of the student's move*, not the introduction of another one.
    scopes = (
        [s for s in sentences if _mentions(s, move_san)],
        [s for s in sentences if not _ALTERNATIVE.search(s)],
        sentences,
    )
    for scope in scopes:
        if not scope:
            continue
        text = " ".join(scope)
        negatives = len(_NEG_RE.findall(_MINIMISED.sub(" ", text)))
        positives = len(_POS_RE.findall(text))
        if negatives > positives:
            return "bad"
        if positives > negatives:
            return "sound"
    return "unclear"


def _move_san(golden: dict) -> str:
    """The SAN of the move the student proposed, as written in the question."""
    found = re.search(r"playing ([^\s]+) here", golden.get("student_message", ""))
    return found.group(1) if found else ""


# A long run of back-to-back turns runs into provider rate limits, which arrive as
# a failed turn rather than a wait. Retrying with a widening pause turns a run that
# collapses two-thirds of the way through into one that merely takes longer.
RETRIES = 4
BACKOFF_S = 30.0

# A steady gap between turns keeps a long run under the provider's rate limit. Left
# at zero the run is faster but tends to collapse partway through, which costs far
# more time than the pause it saved.
PACE_S = 5.0


async def _ask(coach: AgentCoach, golden: dict) -> tuple[str, float]:
    """Put one student question to the coach, returning the reply and its latency.

    Only the successful attempt is timed, so a retried turn does not inflate the
    latency distribution with the provider's back-off.
    """
    last: Exception | None = None
    for attempt in range(RETRIES):
        started = time.perf_counter()
        try:
            reply = await coach.teach(
                golden["fen"], golden["student_message"], "intermediate"
            )
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised if final
            last = exc
            if attempt < RETRIES - 1:
                await anyio.sleep(BACKOFF_S * (attempt + 1))
            continue
        return reply, (time.perf_counter() - started) * 1000.0
    assert last is not None
    raise last


@contextlib.contextmanager
def ablate_refutation() -> Iterator[None]:
    """Restore the tool's *old* contract: a grade with no consequence.

    Isolates the value of returning the opponent's reply and line. The tool still
    answers "how far from best is this move?" — the coach simply cannot see what
    happens after it, which is what the pre-change ``evaluate_move`` looked like.
    """
    from chess_coach.adapters.coach import tools as tools_mod

    original = tools_mod.evaluate_move

    def graded_only(analyzer, fen, move):  # type: ignore[no-untyped-def]
        result = original(analyzer, fen, move)
        return replace(result, reply_san="", line_san=())

    tools_mod.evaluate_move = graded_only  # type: ignore[assignment]
    try:
        yield
    finally:
        tools_mod.evaluate_move = original  # type: ignore[assignment]


@contextlib.contextmanager
def ablate_move_tool() -> Iterator[None]:
    """Withhold ``evaluate_move`` from the agent for the duration of a run.

    The control arm of the value experiment. ``allowed_tools`` is the outer gate —
    a tool absent from it is unreachable however the loaded skill's frontmatter is
    written — so dropping the name here is enough to make the coach judge the
    student's move by reasoning alone, which is exactly the "before" this feature
    has to beat.
    """
    from chess_coach.adapters.coach import agent as agent_mod

    original = list(agent_mod._ALL_TOOLS)
    agent_mod._ALL_TOOLS[:] = [t for t in original if t != agent_mod._EVALUATE]
    try:
        yield
    finally:
        agent_mod._ALL_TOOLS[:] = original


async def run(
    goldens: list[dict], depth: int, pace: float = PACE_S
) -> tuple[list[Outcome], list[str]]:
    outcomes: list[Outcome] = []
    errors: list[str] = []
    with StockfishAnalyzer(depth=depth) as engine:
        coach = AgentCoach(MemoizingAnalyzer(engine))
        for index, golden in enumerate(goldens, start=1):
            if index > 1 and pace:
                await anyio.sleep(pace)
            try:
                reply, elapsed = await _ask(coach, golden)
            except Exception as exc:  # noqa: BLE001 - one bad turn must not end the run
                # anyio wraps failures in an ExceptionGroup whose str() hides the
                # cause ("1 sub-exception"), which is exactly what you need to see.
                detail = "; ".join(
                    f"{type(e).__name__}: {e}"
                    for e in getattr(exc, "exceptions", None) or [exc]
                )
                errors.append(f"{golden['id']}: {detail}")
                print(
                    f"  [{index}/{len(goldens)}] {golden['id']}: ERROR {detail[:160]}",
                    file=sys.stderr,
                )
                continue
            move_san = _move_san(golden)
            verdict = classify(reply, move_san)
            expected_sound = bool(golden["_expected_sound"])
            correct = verdict == ("sound" if expected_sound else "bad")
            expected_reply = golden.get("_expected_reply", "")
            named = names_move(reply, expected_reply)
            outcomes.append(
                Outcome(
                    id=golden["id"],
                    expected_sound=expected_sound,
                    verdict=verdict,
                    correct=correct,
                    cp_loss=int(golden["_cp_loss"]),
                    latency_ms=elapsed,
                    reply_chars=len(reply),
                    move_san=move_san,
                    reply=reply,
                    expected_reply=expected_reply,
                    named_reply=named,
                )
            )
            mark = "OK " if correct else "MISS"
            print(
                f"  [{index}/{len(goldens)}] {mark} {golden['id']:<28} "
                f"said={verdict:<7} reason={'Y' if named else 'n'} "
                f"{elapsed / 1000:5.1f}s",
                file=sys.stderr,
            )
    return outcomes, errors


# Below this share of the dataset actually scored, the run is a failed run and its
# accuracy is not a measurement of anything. Reporting "100%" over the 3 turns that
# happened to survive is worse than reporting nothing.
MIN_COVERAGE = 0.8


def summarize(outcomes: list[Outcome], attempted: int | None = None) -> dict:
    """Accuracy split by band, plus the latency distribution of the same run.

    ``attempted`` is the number of problems the run set out to answer; when far
    fewer were scored the summary is marked ``valid: False`` so a broken run can
    never be quoted as a result.
    """
    scored = len(outcomes)
    correct = sum(1 for o in outcomes if o.correct)
    sound = [o for o in outcomes if o.expected_sound]
    bad = [o for o in outcomes if not o.expected_sound]
    samples = [o.latency_ms for o in outcomes]
    total = attempted if attempted is not None else scored
    coverage = (scored / total) if total else 0.0
    return {
        "n": scored,
        "attempted": total,
        "coverage": coverage,
        "valid": bool(total) and coverage >= MIN_COVERAGE,
        "accuracy": (correct / scored) if scored else 0.0,
        "accuracy_sound": (sum(o.correct for o in sound) / len(sound)) if sound else 0.0,
        "accuracy_bad": (sum(o.correct for o in bad) / len(bad)) if bad else 0.0,
        "unclear": sum(1 for o in outcomes if o.verdict == "unclear"),
        # The reason axis. ``taught`` is the one that matters: a right verdict backed
        # by the concrete reply. A right verdict alone is a grade, not a lesson.
        "named_reply": (
            (sum(1 for o in outcomes if o.named_reply) / scored) if scored else 0.0
        ),
        "taught": (
            (sum(1 for o in outcomes if o.correct and o.named_reply) / scored)
            if scored
            else 0.0
        ),
        "latency_p50_ms": latency.percentile(samples, 0.50),
        "latency_p90_ms": latency.percentile(samples, 0.90),
        "latency_mean_ms": (sum(samples) / scored) if scored else 0.0,
        "reply_chars_p50": latency.percentile(
            [float(o.reply_chars) for o in outcomes], 0.50
        ),
    }


def _regrade(source: Path, out: Path, goldens_path: Path) -> int:
    """Re-score a finished run's stored replies with the current grader.

    The ground truth is re-read from the goldens rather than trusted from the
    previous result file, so every axis is recomputed and a regrade can never
    silently drop one it does not know about.
    """
    previous = json.loads(source.read_text())
    truth = {g["id"]: g for g in json.loads(goldens_path.read_text())}
    outcomes: list[Outcome] = []
    for row in previous["outcomes"]:
        golden = truth.get(row["id"], {})
        verdict = classify(row["reply"], row.get("move_san"))
        expected_reply = golden.get("_expected_reply", row.get("expected_reply", ""))
        outcomes.append(
            Outcome(
                id=row["id"],
                expected_sound=row["expected_sound"],
                verdict=verdict,
                correct=verdict == ("sound" if row["expected_sound"] else "bad"),
                cp_loss=row["cp_loss"],
                latency_ms=row["latency_ms"],
                reply_chars=row["reply_chars"],
                move_san=row.get("move_san", ""),
                reply=row["reply"],
                expected_reply=expected_reply,
                named_reply=names_move(row["reply"], expected_reply),
            )
        )
        if verdict != row["verdict"]:
            print(
                f"  {row['id']:<28} {row['verdict']} -> {verdict}",
                file=sys.stderr,
            )
    summary = summarize(outcomes)
    target = out if out.is_absolute() else RESULTS_DIR / out
    target.write_text(
        json.dumps(
            {"summary": summary, "outcomes": [asdict(o) for o in outcomes]}, indent=2
        )
        + "\n"
    )
    print(
        f"regraded {summary['n']}: accuracy {summary['accuracy']:.0%} "
        f"(sound {summary['accuracy_sound']:.0%}, bad {summary['accuracy_bad']:.0%}, "
        f"unclear {summary['unclear']}) | named {summary['named_reply']:.0%} "
        f"| TAUGHT {summary['taught']:.0%} -> {target}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goldens", type=Path, default=GOLDENS)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=18)
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    parser.add_argument("--pace", type=float, default=PACE_S,
                        help="seconds to wait between turns (rate-limit headroom)")
    parser.add_argument(
        "--regrade",
        type=Path,
        help="re-score the stored replies of a previous run instead of calling the "
        "coach — lets the grader be fixed without paying for another live run",
    )
    parser.add_argument(
        "--ablate-refutation",
        action="store_true",
        help="control arm: strip reply/line from evaluate_move (its old contract)",
    )
    parser.add_argument(
        "--ablate-move-tool",
        action="store_true",
        help="control arm: withhold evaluate_move so the coach must judge by reasoning",
    )
    args = parser.parse_args(argv)

    if args.regrade:
        return _regrade(args.regrade, args.out, args.goldens)

    goldens = json.loads(args.goldens.read_text())
    if args.limit:
        goldens = goldens[: args.limit]
    print(f"running {len(goldens)} move-evaluation problems", file=sys.stderr)

    latency.reset()
    with contextlib.ExitStack() as stack:
        if args.ablate_move_tool:
            print("ABLATION: evaluate_move withheld from the agent", file=sys.stderr)
            stack.enter_context(ablate_move_tool())
        if args.ablate_refutation:
            print("ABLATION: evaluate_move returns no reply/line", file=sys.stderr)
            stack.enter_context(ablate_refutation())
        outcomes, errors = anyio.run(run, goldens, args.depth, args.pace)
    summary = summarize(outcomes, attempted=len(goldens))
    summary["errors"] = errors

    out = args.out if args.out.is_absolute() else RESULTS_DIR / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"summary": summary, "outcomes": [asdict(o) for o in outcomes]}, indent=2
        )
        + "\n"
    )

    print("\n=== move-evaluation ===", file=sys.stderr)
    print(
        f"scored        {summary['n']}/{summary['attempted']} "
        f"({summary['coverage']:.0%} coverage, {len(errors)} errors)",
        file=sys.stderr,
    )
    if not summary["valid"]:
        print(
            "INVALID RUN — too much of the dataset failed; the accuracy below is "
            "not a measurement. Re-run before quoting it.",
            file=sys.stderr,
        )
        for err in errors[:3]:
            print(f"  first errors: {err[:200]}", file=sys.stderr)
    print(
        f"accuracy      {summary['accuracy']:.0%}  "
        f"(sound {summary['accuracy_sound']:.0%}, bad {summary['accuracy_bad']:.0%}, "
        f"unclear {summary['unclear']})",
        file=sys.stderr,
    )
    print(
        f"named reply   {summary['named_reply']:.0%}   "
        f"TAUGHT (verdict+reason) {summary['taught']:.0%}",
        file=sys.stderr,
    )
    print(
        f"latency       p50={summary['latency_p50_ms'] / 1000:.1f}s  "
        f"p90={summary['latency_p90_ms'] / 1000:.1f}s",
        file=sys.stderr,
    )
    print(f"wrote {out}", file=sys.stderr)
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Evaluate the prose (judge-graded) coaching tasks with Codex, cheaply.

The deterministic scoreboard is saturated (best_move/eval_bucket/endgame are grounded
at ceiling); the real coaching headroom is the *prose* tasks — teaching, mistake
diagnosis, general chat, and multi-turn conversation — graded by the deepeval ``GEval``
judges. Those default to Claude and need an API key; here they run with an injected
:class:`~evals.harness.codex_judge.CodexJudge`, so the criteria and harness are
unchanged and only the judge model differs.

To make the harness's contribution measurable it runs an A/B:

* ``--variant naive`` — a bare "you are a chess coach" prompt: no engine grounding,
  no spoiler control, no transcript. The strawman.
* ``--variant grounded`` — the real :class:`CodexCoach` prose turns: Stockfish facts
  embedded, spoiler-aware teaching, transcript-aware conversation.

The gap between them is the value of the coaching scaffolding.

    uv run python -m evals.tools.run_codex_judged --per-task 2 --variant naive
    uv run python -m evals.tools.run_codex_judged --per-task 2 --variant grounded
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import anyio

from chess_coach.adapters.coach.analysis import DEFAULT_DEPTH, StockfishAnalyzer
from chess_coach.adapters.coach.codex_agent import CodexCoach
from chess_coach.adapters.coach.opening_book import OpeningBook
from evals.data.loader import (
    coach_input,
    load_goldens,
    stratified_sample,
    to_conversation_case,
    to_general_chat_case,
    to_mistake_case,
    to_teaching_case,
)
from evals.data.schema import ChessGolden
from evals.harness.agent_task import answer_for_input
from evals.harness.codex_judge import CodexJudge, codex_exec_text
from evals.harness.legality import check_result
from evals.harness.task import CoachResult
from evals.metrics.conversation_judge import conversation_quality_metric
from evals.metrics.general_chat import general_chat_quality_metric
from evals.metrics.mistake import mistake_diagnosis_quality_metric
from evals.metrics.teaching import teaching_quality_metric
from evals.tools.run_codex import LockingAnalyzer

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"

JUDGED_TASKS = ("teaching", "mistake_diagnosis", "general_chat", "conversation")

# task -> (GEval metric factory, deepeval test-case builder)
_JUDGES: dict[str, tuple[Callable[..., object], Callable[..., object]]] = {
    "teaching": (teaching_quality_metric, to_teaching_case),
    "mistake_diagnosis": (mistake_diagnosis_quality_metric, to_mistake_case),
    "general_chat": (general_chat_quality_metric, to_general_chat_case),
    "conversation": (conversation_quality_metric, to_conversation_case),
}


def _naive_answer(golden: ChessGolden) -> str:
    """A strawman coach: the student's turn, no grounding/spoiler-rule/memory."""
    parts = ["You are a chess coach. Answer the student helpfully."]
    if golden.level:
        parts.append(f"Student level: {golden.level}")
    if golden.fen:
        parts.append(f"Position FEN: {golden.fen}")
    if golden.student_move:
        parts.append(f"The student is considering the move {golden.student_move}.")
    parts.append(f'Student: "{golden.student_message or ""}"')
    return codex_exec_text("\n".join(parts), reasoning_effort="low").strip()


def _grounded_answer(coach: CodexCoach, golden: ChessGolden) -> str:
    """The real CodexCoach prose turn (grounded, spoiler/transcript aware)."""
    return answer_for_input(coach, coach_input(golden)).explanation


def _selective_answer(coach: CodexCoach, golden: ChessGolden) -> str:
    """Selective grounding: full facts for conversation/general chat, but assessment-
    only (no engine best move) for teaching/diagnosis so the coach isn't over-steered
    to the engine's specific move over a curated one."""
    if golden.task == "teaching":
        return coach.teach_light_sync(
            golden.fen or "", golden.student_message or "", golden.level
        )
    if golden.task == "mistake_diagnosis":
        return coach.diagnose_light_sync(
            golden.fen or "",
            golden.student_move,
            golden.student_message or "",
            golden.level,
        )
    return _grounded_answer(coach, golden)


def _judge(
    golden: ChessGolden, prose: str, judge_model: CodexJudge
) -> tuple[float, str]:
    factory, build_case = _JUDGES[golden.task]
    metric = factory(model=judge_model)
    case = build_case(golden, CoachResult(explanation=prose))
    score = float(metric.measure(case))  # type: ignore[attr-defined]
    return score, str(getattr(metric, "reason", "") or "")


def _fp(variant: str, model: str | None, effort: str, depth: int) -> str:
    raw = f"judged|{variant}|{model}|{effort}|{depth}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


async def _gather(
    goldens: list[ChessGolden],
    answer_fn: Callable[[ChessGolden], str],
    judge_model: CodexJudge,
    fp: str,
    *,
    concurrency: int,
    use_cache: bool,
    pv_provider: Callable[[str], list[str]] | None = None,
) -> dict[str, dict[str, object]]:
    cache = _load_cache_for(fp) if use_cache else {}
    out: dict[str, dict[str, object]] = {}
    limiter = anyio.CapacityLimiter(concurrency)
    lock = anyio.Lock()

    async def one(golden: ChessGolden) -> None:
        key = f"{fp}|{golden.id}"
        if use_cache and key in cache:
            row = dict(cache[key])
            # Recompute legality (cheap, engine-only) from the cached prose so an
            # improved check applies without re-running the model.
            prose = str(row.get("prose") or "")
            line = None
            if pv_provider and golden.fen:
                line = await anyio.to_thread.run_sync(pv_provider, golden.fen)
            legality = check_result(golden.fen, line=line, explanation=prose)
            row["legal"] = legality.legal
            row["illegal_moves"] = list(legality.illegal)
            out[golden.id] = row
            print(f"  cached  {golden.id} ({golden.task}) score={row['score']}")
            return
        async with limiter:
            prose = await anyio.to_thread.run_sync(answer_fn, golden)
            score, reason = await anyio.to_thread.run_sync(
                _judge, golden, prose, judge_model
            )
        # Anchor prose legality to the engine's best line so a coach discussing a
        # king march or forcing line is not mistaken for naming illegal moves.
        line = None
        if pv_provider and golden.fen:
            line = await anyio.to_thread.run_sync(pv_provider, golden.fen)
        legality = check_result(golden.fen, line=line, explanation=prose)
        row = {
            "task": golden.task,
            "score": score,
            "reason": reason,
            "prose": prose,
            "legal": legality.legal,
            "illegal_moves": list(legality.illegal),
        }
        out[golden.id] = row
        print(f"  ran     {golden.id} ({golden.task}) score={score:.2f}")
        if use_cache:
            async with lock:
                cache[key] = row
                _save_cache(fp, cache)

    async with anyio.create_task_group() as tg:
        for golden in goldens:
            tg.start_soon(one, golden)
    return out


# The cache is keyed only by fingerprint, so store it under one file per variant fp.
_CACHE_STORE = RESULTS_DIR / "codex_judged_cache.json"


def _load_cache_for(fp: str) -> dict[str, dict[str, object]]:
    try:
        data = json.loads(_CACHE_STORE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get(fp, {}) if isinstance(data, dict) else {}


def _save_cache(fp: str, rows: dict[str, dict[str, object]]) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    try:
        data = json.loads(_CACHE_STORE.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[fp] = rows
    _CACHE_STORE.write_text(json.dumps(data, indent=2) + "\n")


def _summarize(
    rows: dict[str, dict[str, Any]], threshold: float
) -> dict[str, dict[str, Any]]:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows.values():
        by_task[str(row["task"])].append(row)
    by_task_all = dict(by_task)
    by_task_all["overall"] = [r for rs in by_task.values() for r in rs]
    summary: dict[str, dict[str, Any]] = {}
    for task, task_rows in by_task_all.items():
        scores = [float(r["score"]) for r in task_rows]
        n = len(scores)
        passed = sum(1 for s in scores if s >= threshold)
        legal = sum(1 for r in task_rows if r.get("legal", True))
        summary[task] = {
            "n": n,
            "passed": passed,
            "pass_rate": passed / n if n else 0.0,
            "mean_score": sum(scores) / n if n else 0.0,
            "legal_rate": legal / n if n else 1.0,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-task", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--variant",
        choices=("naive", "grounded", "selective"),
        default="grounded",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--effort", default="low")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--threshold", type=float, default=0.7)
    parser.add_argument(
        "--tasks",
        default=",".join(JUDGED_TASKS),
        help="comma-separated judged tasks to include",
    )
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    tasks = tuple(t.strip() for t in args.tasks.split(",") if t.strip())
    goldens = stratified_sample(
        load_goldens(), per_task=args.per_task, tasks=tasks, seed=args.seed
    )
    fp = _fp(args.variant, args.model, args.effort, args.depth)
    judge_model = CodexJudge(model=args.model, reasoning_effort=args.effort)
    print(
        f"judging {len(goldens)} prose goldens | variant={args.variant} "
        f"effort={args.effort} fp={fp}"
    )

    with StockfishAnalyzer(depth=args.depth) as sf:
        analyzer = LockingAnalyzer(sf)
        coach = CodexCoach(
            analyzer,
            OpeningBook(),
            model=args.model,
            reasoning_effort=args.effort,
        )
        if args.variant == "naive":
            answer_fn: Callable[[ChessGolden], str] = _naive_answer
        elif args.variant == "selective":
            answer_fn = partial(_selective_answer, coach)
        else:
            answer_fn = partial(_grounded_answer, coach)

        def pv_provider(fen: str) -> list[str]:
            try:
                return list(analyzer.analyze(fen).pv_uci)
            except (ValueError, RuntimeError):
                return []

        rows = anyio.run(
            partial(
                _gather,
                goldens,
                answer_fn,
                judge_model,
                fp,
                concurrency=args.concurrency,
                use_cache=not args.refresh,
                pv_provider=pv_provider,
            )
        )

    summary = _summarize(rows, args.threshold)
    print()
    for task in (*JUDGED_TASKS, "overall"):
        if task in summary:
            s = summary[task]
            print(
                f"{task:18} {s['passed']}/{s['n']} passed "
                f"({s['pass_rate']:.0%}), mean score {s['mean_score']:.2f}, "
                f"legal {s['legal_rate']:.0%}"
            )
    illegal = {
        gid: r["illegal_moves"] for gid, r in rows.items() if not r.get("legal", True)
    }
    for gid, moves in illegal.items():
        print(f"  ILLEGAL {gid}: {moves}")

    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"codex_judged_{args.variant}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "variant": args.variant,
                "effort": args.effort,
                "per_task": args.per_task,
                "seed": args.seed,
                "threshold": args.threshold,
                "summary": summary,
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

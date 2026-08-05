"""Grade the real coach cheaply with a Codex model over a representative sample.

The counterpart to :mod:`evals.tools.run_agent` (the Claude coach) built for *fast,
cheap iteration*: it drives :class:`~chess_coach.adapters.coach.codex_agent.CodexCoach`
— which grounds every structured field in Stockfish before the model speaks — over a
stratified slice of the deterministic tasks, scores it with the same metrics the
pytest gate uses, and writes a labelled report so a baseline and a treatment run can
be compared honestly.

Why Codex at low reasoning effort: on a ChatGPT-account CLI the small models are
unavailable, so the cheap lever is ``model_reasoning_effort=low``. The engine call
is serialized (one Stockfish process is not concurrency-safe) while the Codex
subprocesses run in parallel, so wall-clock is bounded by the model, not the engine.

    uv run python -m evals.tools.run_codex --per-task 3 --label baseline
    uv run python -m evals.tools.run_codex --per-task 3 --label treatment --refresh
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import anyio

from chess_coach.adapters.coach import tools
from chess_coach.adapters.coach.agent import _parse_answer
from chess_coach.adapters.coach.analysis import (
    DEFAULT_DEPTH,
    PositionAnalysis,
    PositionAnalyzer,
    StockfishAnalyzer,
)
from chess_coach.adapters.coach.codex_agent import CodexCoach
from chess_coach.adapters.coach.opening_book import OpeningBook
from chess_coach.adapters.observability import tracing
from evals.data.loader import (
    DETERMINISTIC_TASKS,
    coach_input,
    load_goldens,
    stratified_sample,
    to_test_case,
)
from evals.data.schema import ChessGolden
from evals.harness.agent_task import answer_for_input
from evals.harness.codex_judge import codex_exec_text
from evals.harness.legality import check_result
from evals.harness.task import CoachResult
from evals.tools.report import Record, metric_for, summarize

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
_CACHE_PATH = RESULTS_DIR / "codex_cache.json"

# Cheap, fast defaults for the iteration loop. gpt-5.5 is the ChatGPT-account
# default; "low" effort keeps each turn short.
DEFAULT_EFFORT = "low"


class LockingAnalyzer:
    """Serialize access to a single, non-reentrant engine process behind a lock.

    The Codex answers run concurrently (each spawns its own subprocess), but they
    all ground through one Stockfish process, and driving one UCI engine from
    several threads at once corrupts its state. The lock makes each probe atomic;
    the engine call is ~1s while a Codex turn is ~10s, so this costs almost nothing.
    """

    def __init__(self, inner: PositionAnalyzer) -> None:
        self._inner = inner
        self._lock = threading.Lock()

    def analyze(self, fen: str) -> PositionAnalysis:
        with self._lock:
            return self._inner.analyze(fen)

    def top_moves(self, fen: str, n: int = 3) -> list:
        """Delegate MultiPV to the wrapped analyzer under the same lock."""
        with self._lock:
            return self._inner.top_moves(fen, n)


def _fingerprint(
    model: str | None, effort: str | None, depth: int, solve: str | None = None
) -> str:
    """Invalidate cached answers when model, effort, depth, or solve mode changes."""
    raw = f"codex|{model}|{effort}|{depth}|solve={solve}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _cache_key(fp: str, golden: ChessGolden) -> str:
    raw = f"{fp}|{golden.task}|{golden.level}|{golden.fen}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_cache() -> dict[str, dict[str, object]]:
    try:
        data = json.loads(_CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict[str, dict[str, object]]) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2) + "\n")


# Un-grounded solve mode: the coach is NOT handed the engine's answer, so the metric
# scores its own solving ability (real headroom) rather than whether it echoed the
# engine. "aided" adds a rules-only tactical scan (legal checks/captures/loose pieces)
# — reasoning support, never the answer — so the lift from it is a genuine harness gain.
_SOLVE_SYSTEM = (
    "You are solving a chess position yourself. No engine evaluation is provided. "
    "Reason briefly, then commit to a concrete answer. Only ever name legal moves."
)

_SOLVE_BRIEF: dict[str, str] = {
    "best_move": (
        "Find the single best move. Report `best_move` as a UCI string (e.g. e1e8)."
    ),
    "eval_bucket": (
        "Assess who stands better from the side to move. Report `eval_bucket` as "
        "exactly one of: losing, worse, equal, better, winning."
    ),
    "endgame": (
        "Find the key move and the game result. Report `best_move` (UCI) and `result` "
        "as one of: win, draw, loss."
    ),
    "deep_line": (
        "Give the best line for both sides. Report `best_move` (UCI) and `line` as a "
        "JSON array of UCI moves, alternating sides."
    ),
}


def _solve_answer(
    fen: str,
    task_type: str,
    *,
    aided: bool,
    model: str | None,
    effort: str,
) -> CoachResult:
    """Solve a position without being given the engine's answer (optionally aided)."""
    aid_block = ""
    if aided:
        f = tools.position_features(fen)
        scan = {
            "side_to_move": f.side_to_move,
            "in_check": f.in_check,
            "legal_checks": f.checks,
            "captures": f.captures,
            "enemy_loose_pieces": f.hanging_targets,
            "your_loose_pieces": f.hanging_own,
            "material": f.material,
        }
        aid_block = (
            "Rules-only tactical scan (facts from the position, NOT the answer):\n"
            f"```json\n{json.dumps(scan, indent=2)}\n```\n"
        )
    prompt = (
        f"{_SOLVE_SYSTEM}\n\n"
        f"Position FEN: {fen}\n"
        f"Task: {_SOLVE_BRIEF[task_type]}\n"
        f"{aid_block}\n"
        "End with one fenced JSON block: "
        '{"best_move": "<uci or null>", "eval_bucket": "<bucket or null>", '
        '"result": "<win|draw|loss or null>", "line": ["<uci>"], '
        '"explanation": "<one sentence>"}'
    )
    text = codex_exec_text(prompt, model=model, reasoning_effort=effort)
    answer = _parse_answer(text)
    return CoachResult(
        best_move=answer.best_move,
        eval_bucket=answer.eval_bucket,
        result=answer.result,  # type: ignore[arg-type]
        line=answer.line,
        explanation=answer.explanation,
    )


async def _gather(
    coach: CodexCoach,
    goldens: list[ChessGolden],
    fp: str,
    *,
    concurrency: int,
    use_cache: bool,
    solve: str | None = None,
    model: str | None = None,
    effort: str = DEFAULT_EFFORT,
) -> dict[str, CoachResult]:
    cache = _load_cache() if use_cache else {}
    results: dict[str, CoachResult] = {}
    limiter = anyio.CapacityLimiter(concurrency)
    lock = anyio.Lock()

    async def one(golden: ChessGolden) -> None:
        key = _cache_key(fp, golden)
        if use_cache and key in cache:
            e = cache[key]
            results[golden.id] = CoachResult(
                best_move=e.get("best_move"),  # type: ignore[arg-type]
                eval_bucket=e.get("eval_bucket"),  # type: ignore[arg-type]
                result=e.get("result"),  # type: ignore[arg-type]
                line=e.get("line"),  # type: ignore[arg-type]
                explanation=str(e.get("explanation") or ""),
            )
            print(f"  cached  {golden.id}")
            return
        async with limiter:
            if solve:
                answer = await anyio.to_thread.run_sync(
                    partial(
                        _solve_answer,
                        golden.fen or "",
                        golden.task,
                        aided=solve == "aided",
                        model=model,
                        effort=effort,
                    )
                )
            else:
                answer = await anyio.to_thread.run_sync(
                    answer_for_input, coach, coach_input(golden)
                )
        results[golden.id] = CoachResult(
            best_move=answer.best_move,
            eval_bucket=answer.eval_bucket,
            result=answer.result,  # type: ignore[arg-type]
            line=answer.line,
            explanation=answer.explanation,
        )
        print(f"  ran     {golden.id}: move={answer.best_move} line={answer.line}")
        if use_cache:
            async with lock:
                cache[key] = {
                    "best_move": answer.best_move,
                    "eval_bucket": answer.eval_bucket,
                    "result": answer.result,
                    "line": answer.line,
                    "explanation": answer.explanation,
                }
                _save_cache(cache)

    async with anyio.create_task_group() as tg:
        for golden in goldens:
            tg.start_soon(one, golden)
    return results


def _grade(
    goldens: list[ChessGolden], results: dict[str, CoachResult]
) -> list[Record]:
    records: list[Record] = []
    for golden in goldens:
        metric = metric_for(golden.task)
        score = metric.measure(to_test_case(golden, results[golden.id]))
        records.append(
            Record(
                id=golden.id,
                task=golden.task,
                score=score,
                success=metric.is_successful(),
                reason=metric.reason,
            )
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-task", type=int, default=3, help="goldens per task")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--model", default=None, help="codex model (else CLI default)")
    parser.add_argument("--effort", default=DEFAULT_EFFORT, help="reasoning effort")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--label", default="codex", help="report label")
    parser.add_argument(
        "--solve",
        choices=("plain", "aided"),
        default=None,
        help="un-grounded: coach solves the position itself (no engine answer given); "
        "'aided' adds a rules-only tactical scan",
    )
    parser.add_argument("--refresh", action="store_true", help="ignore the cache")
    args = parser.parse_args()

    # Opt-in tracing so a run can be inspected in Phoenix; off by default (cheap
    # no-op). Enable with CHESS_COACH_TRACING_ENABLED=1 and open http://localhost:6006.
    traced = tracing.configure_tracing(
        enabled=os.environ.get("CHESS_COACH_TRACING_ENABLED") == "1",
        otlp_endpoint=os.environ.get(
            "CHESS_COACH_OTLP_ENDPOINT", "http://localhost:6006/v1/traces"
        ),
    )

    goldens = stratified_sample(
        load_goldens(),
        per_task=args.per_task,
        tasks=DETERMINISTIC_TASKS,
        seed=args.seed,
    )
    fp = _fingerprint(args.model, args.effort, args.depth, args.solve)
    print(
        f"grading {len(goldens)} goldens with codex model={args.model or 'CLI-default'}"
        f" effort={args.effort} depth={args.depth} solve={args.solve} fp={fp}"
    )

    with StockfishAnalyzer(depth=args.depth) as sf:
        coach = CodexCoach(
            LockingAnalyzer(sf),
            OpeningBook(),
            model=args.model,
            reasoning_effort=args.effort,
        )
        results = anyio.run(
            partial(
                _gather,
                coach,
                goldens,
                fp,
                concurrency=args.concurrency,
                use_cache=not args.refresh,
                solve=args.solve,
                model=args.model,
                effort=args.effort,
            )
        )

    records = _grade(goldens, results)
    summary = summarize(records)
    # Deterministic legality check on every LLM result (structured move + line + prose).
    legality = {
        g.id: check_result(
            g.fen,
            best_move=results[g.id].best_move,
            line=results[g.id].line,
            explanation=results[g.id].explanation,
        )
        for g in goldens
    }
    legal_rate = sum(1 for lr in legality.values() if lr.legal) / len(legality)
    print()
    for task in ("best_move", "deep_line", "eval_bucket", "endgame", "overall"):
        if task in summary:
            s = summary[task]
            print(
                f"{task:11} {int(s['passed'])}/{int(s['n'])} passed "
                f"({s['pass_rate']:.0%}), mean score {s['mean_score']:.2f}"
            )
    print(f"legality    {legal_rate:.0%} of results name only legal moves")
    for r in records:
        if not r["success"]:
            print(f"  FAIL {r['id']}: {r['reason']}")
    for gid, lr in legality.items():
        if not lr.legal:
            print(f"  ILLEGAL {gid}: {lr.illegal}")

    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"codex_{args.label}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "label": args.label,
                "model": args.model,
                "effort": args.effort,
                "per_task": args.per_task,
                "seed": args.seed,
                "summary": summary,
                "records": records,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nwrote {path}")
    if traced:
        # BatchSpanProcessor exports asynchronously; flush before the process exits
        # or the run's spans never reach Phoenix.
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
        print("flushed traces to Phoenix (http://localhost:6006)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

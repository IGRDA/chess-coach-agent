"""Run the real Claude coach over the dataset, concurrently, and score it.

The counterpart to :mod:`evals.tools.report` (which grades the reference oracle):
this drives the actual :class:`~chess_coach.adapters.coach.agent.AgentCoach` over
every golden, fills the shared answer cache that ``COACH_TASK=agent`` reads, and
prints/writes the same per-task scoreboard.

Why it lives apart from ``report``: the agent is slow (a live model call per
position), so answers are gathered *concurrently* and *memoised*. The in-process
engine tool is safe to share across those concurrent calls because tool callbacks
run cooperatively in one event loop and each engine probe is atomic (no ``await``
inside it). After a run, ``uv run pytest evals/ -m "not judge"`` with
``COACH_TASK=agent`` is instant — it just reads the cache this populated.

    uv run python -m evals.tools.run_agent                 # all goldens
    uv run python -m evals.tools.run_agent --limit 3       # a quick subset
    uv run python -m evals.tools.run_agent --refresh       # ignore the cache
"""

from __future__ import annotations

import argparse
import sys
from functools import partial

import anyio

from chess_coach.adapters.coach.agent import AgentCoach, CoachAnswer
from chess_coach.adapters.coach.opening_book import OpeningBook
from chess_coach.adapters.observability import tracing
from chess_coach.composition.config import Settings
from evals.data.loader import coach_input, load_goldens, to_test_case
from evals.data.schema import ChessGolden
from evals.harness.agent_task import (
    OracleAnalyzer,
    _answer_from_cache,
    _fingerprint,
    _load_cache,
    _save_cache,
    aanswer_for_input,
    cache_key,
)
from evals.harness.engine import StockfishOracle
from evals.harness.task import CoachResult
from evals.tools.report import (
    DETERMINISTIC_TASKS,
    Record,
    metric_for,
    summarize,
    write_report,
)


async def _gather(
    coach: AgentCoach,
    goldens: list[ChessGolden],
    fp: str,
    *,
    concurrency: int,
    use_cache: bool,
) -> dict[str, CoachAnswer]:
    cache = _load_cache() if use_cache else {}
    answers: dict[str, CoachAnswer] = {}
    limiter = anyio.CapacityLimiter(concurrency)
    lock = anyio.Lock()

    async def one(golden: ChessGolden) -> None:
        ci = coach_input(golden)
        key = cache_key(
            fp,
            ci.task_type,
            ci.level,
            ci.fen,
            ci.context,
            ci.candidate_move,
            ci.conversation_history,
        )
        if golden.task == "multi_turn_teaching":
            print(f"  skipped {golden.id}: needs transcript runner")
            return
        if use_cache and key in cache:
            answers[golden.id] = _answer_from_cache(cache[key])
            print(f"  cached  {golden.id}")
            return
        async with limiter:
            answer = await aanswer_for_input(coach, ci)
        answers[golden.id] = answer
        print(
            f"  ran     {golden.id}: move={answer.best_move} "
            f"bucket={answer.eval_bucket} result={answer.result}"
        )
        if use_cache:
            async with lock:
                cache[key] = {
                    "best_move": answer.best_move,
                    "eval_bucket": answer.eval_bucket,
                    "result": answer.result,
                    "line": answer.line,
                    "explanation": answer.explanation,
                    "raw": "",
                }
                _save_cache(cache)

    async with anyio.create_task_group() as tg:
        for golden in goldens:
            tg.start_soon(one, golden)
    return answers


def _grade(goldens: list[ChessGolden], answers: dict[str, CoachAnswer]) -> list[Record]:
    records: list[Record] = []
    for golden in goldens:
        answer = answers[golden.id]
        result = CoachResult(
            best_move=answer.best_move,
            eval_bucket=answer.eval_bucket,
            result=answer.result,  # type: ignore[arg-type]
            line=answer.line,
            explanation=answer.explanation,
        )
        metric = metric_for(golden.task)
        score = metric.measure(to_test_case(golden, result))
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
    parser.add_argument("--limit", type=int, default=0, help="grade only the first N")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--refresh", action="store_true", help="ignore the cache")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    # Match the application's default-on observability. Set
    # CHESS_COACH_TRACING_ENABLED=0 for a deliberately untraced benchmark.
    settings = Settings()
    traced = tracing.configure_tracing(
        enabled=settings.tracing_enabled,
        otlp_endpoint=settings.otlp_endpoint,
        native_telemetry=settings.native_telemetry,
        native_otlp_endpoint=settings.native_otlp_endpoint,
    )

    goldens = load_goldens()
    if args.limit:
        goldens = goldens[: args.limit]

    with StockfishOracle() as oracle:
        model = args.model
        coach = (
            AgentCoach(OracleAnalyzer(oracle), OpeningBook(), model=model)
            if model
            else AgentCoach(OracleAnalyzer(oracle), OpeningBook())
        )
        fp = _fingerprint(coach._model)
        print(f"grading {len(goldens)} goldens with model={coach._model} fp={fp}")
        answers = anyio.run(
            partial(
                _gather,
                coach,
                goldens,
                fp,
                concurrency=args.concurrency,
                use_cache=not args.refresh,
            )
        )

    # Judge-only turns are filled into the cache above when possible but graded by
    # LLM judges, not deterministic metrics — so leave them out here.
    graded = [g for g in goldens if g.task in DETERMINISTIC_TASKS]
    records = _grade(graded, answers)
    summary = summarize(records)
    print()
    for task in ("best_move", "deep_line", "eval_bucket", "endgame", "overall"):
        if task in summary:
            s = summary[task]
            print(
                f"{task:11} {int(s['passed'])}/{int(s['n'])} passed "
                f"({s['pass_rate']:.0%}), mean score {s['mean_score']:.2f}"
            )
    for r in records:
        if not r["success"]:
            print(f"  FAIL {r['id']}: {r['reason']}")
    path = write_report(records, summary)
    print(f"\nwrote {path}")
    if traced:
        # BatchSpanProcessor exports asynchronously; flush before process exit.
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
        print("flushed traces to Phoenix (http://localhost:6006)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

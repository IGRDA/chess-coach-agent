"""Grade the dataset against a task and write a local score summary.

The deterministic pytest suite is the pass/fail gate; this tool is the at-a-glance
scoreboard. It runs a chosen ``CoachTask`` over every golden, applies the matching
deterministic metric, prints a per-task pass-rate table, and writes
``evals/results/latest.json``. No cloud dashboard — everything stays local.

    uv run python -m evals.tools.report            # grade the reference oracle
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from evals.data.loader import coach_input, load_goldens, to_test_case
from evals.harness.engine import DEFAULT_DEPTH, StockfishOracle
from evals.harness.fakes import OracleTask
from evals.harness.task import CoachTask, TaskType
from evals.metrics import (
    BestMoveMetric,
    DeepLineMetric,
    EndgameTechniqueMetric,
    EvalBucketMetric,
)
from evals.metrics._base import DeterministicMetric

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
DETERMINISTIC_TASKS = ("best_move", "deep_line", "eval_bucket", "endgame")


class Record(TypedDict):
    """One graded golden."""

    id: str
    task: str
    score: float
    success: bool
    reason: str


class Summary(TypedDict):
    """Aggregate scores for one task (or the overall row)."""

    n: int
    passed: int
    pass_rate: float
    mean_score: float


def metric_for(task: TaskType) -> DeterministicMetric:
    """The deterministic metric that grades a given task type."""
    if task == "best_move":
        return BestMoveMetric()
    if task == "deep_line":
        return DeepLineMetric()
    if task == "eval_bucket":
        return EvalBucketMetric()
    if task == "endgame":
        return EndgameTechniqueMetric()
    raise ValueError(f"{task!r} is judge-only; no deterministic metric")


def grade(task: CoachTask) -> list[Record]:
    """Run ``task`` over all goldens and score each with its metric.

    Judge-only goldens (teaching, mistake_diagnosis, multi_turn_teaching,
    general_chat, conversation) are graded by LLM judges, not the deterministic
    metrics, so they are skipped here.
    """
    records: list[Record] = []
    for golden in load_goldens():
        if golden.task not in DETERMINISTIC_TASKS:
            continue
        try:
            result = task(coach_input(golden))
        except NotImplementedError:
            continue
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


def summarize(records: list[Record]) -> dict[str, Summary]:
    """Aggregate per-task pass rate and mean score (plus an ``overall`` row)."""
    buckets: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        buckets[record["task"]].append(record)
    buckets["overall"] = records

    summary: dict[str, Summary] = {}
    for task, rows in buckets.items():
        n = len(rows)
        passed = sum(1 for r in rows if r["success"])
        mean = sum(r["score"] for r in rows) / n if n else 0.0
        summary[task] = Summary(
            n=n, passed=passed, pass_rate=passed / n, mean_score=mean
        )
    return summary


def write_report(records: list[Record], summary: dict[str, Summary]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / "latest.json"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "records": records,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    args = parser.parse_args()

    with StockfishOracle(depth=args.depth) as oracle:
        records = grade(OracleTask(oracle))

    summary = summarize(records)
    for task in ("best_move", "deep_line", "eval_bucket", "endgame", "overall"):
        if task in summary:
            s = summary[task]
            print(
                f"{task:11} {int(s['passed'])}/{int(s['n'])} passed "
                f"({s['pass_rate']:.0%}), mean score {s['mean_score']:.2f}"
            )
    path = write_report(records, summary)
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

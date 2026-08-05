"""Small helpers shared by the dataset-driven tests."""

from __future__ import annotations

import pytest

from evals.data.loader import to_test_case
from evals.data.schema import ChessGolden
from evals.harness.task import CoachInput, CoachResult, CoachTask
from evals.metrics._base import DeterministicMetric


def run_or_xfail(task: CoachTask, task_input: CoachInput) -> CoachResult:
    """Run the task, or xfail cleanly when the coach is the not-yet-built stub.

    This is what keeps the suite green against the reference oracle while marking
    the real-agent target as an expected failure until it is implemented.
    """
    try:
        return task(task_input)
    except NotImplementedError as exc:
        pytest.xfail(str(exc))


def assert_graded(
    metric: DeterministicMetric, golden: ChessGolden, result: CoachResult
) -> None:
    """Grade one answer and assert it passed, surfacing the reason on failure."""
    metric.measure(to_test_case(golden, result))
    assert metric.is_successful(), f"{golden.id}: {metric.reason}"

"""Deep-line eval: the coach must calculate a short continuation."""

from __future__ import annotations

import pytest

from evals.data.loader import coach_input, load_goldens
from evals.data.schema import ChessGolden
from evals.harness.task import CoachTask
from evals.metrics import DeepLineMetric
from evals.tests._support import assert_graded, run_or_xfail

DEEP_LINES = load_goldens("deep_line")


@pytest.mark.parametrize("golden", DEEP_LINES, ids=[g.id for g in DEEP_LINES])
def test_deep_line(golden: ChessGolden, coach_task: CoachTask) -> None:
    result = run_or_xfail(coach_task, coach_input(golden))
    assert_graded(DeepLineMetric(), golden, result)

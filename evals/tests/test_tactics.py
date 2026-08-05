"""Best-move (tactics) eval: the coach's move must be an accepted solution."""

from __future__ import annotations

import pytest

from evals.data.loader import coach_input, load_goldens
from evals.data.schema import ChessGolden
from evals.harness.task import CoachTask
from evals.metrics import BestMoveMetric
from evals.tests._support import assert_graded, run_or_xfail

TACTICS = load_goldens("best_move")


@pytest.mark.parametrize("golden", TACTICS, ids=[g.id for g in TACTICS])
def test_best_move(golden: ChessGolden, coach_task: CoachTask) -> None:
    result = run_or_xfail(coach_task, coach_input(golden))
    assert_graded(BestMoveMetric(), golden, result)

"""Endgame eval: the coach must find the key move and name the result."""

from __future__ import annotations

import pytest

from evals.data.loader import coach_input, load_goldens
from evals.data.schema import ChessGolden
from evals.harness.task import CoachTask
from evals.metrics import EndgameTechniqueMetric
from evals.tests._support import assert_graded, run_or_xfail

ENDGAMES = load_goldens("endgame")


@pytest.mark.parametrize("golden", ENDGAMES, ids=[g.id for g in ENDGAMES])
def test_endgame(golden: ChessGolden, coach_task: CoachTask) -> None:
    result = run_or_xfail(coach_task, coach_input(golden))
    assert_graded(EndgameTechniqueMetric(), golden, result)

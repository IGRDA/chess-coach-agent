"""Position-eval eval: the coach's assessment bucket must match Stockfish's."""

from __future__ import annotations

import pytest

from evals.data.loader import coach_input, load_goldens
from evals.data.schema import ChessGolden
from evals.harness.task import CoachTask
from evals.metrics import EvalBucketMetric
from evals.tests._support import assert_graded, run_or_xfail

POSITIONS = load_goldens("eval_bucket")


@pytest.mark.parametrize("golden", POSITIONS, ids=[g.id for g in POSITIONS])
def test_eval_bucket(golden: ChessGolden, coach_task: CoachTask) -> None:
    result = run_or_xfail(coach_task, coach_input(golden))
    assert_graded(EvalBucketMetric(), golden, result)

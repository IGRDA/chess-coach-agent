"""Eval-bucket metric: does the coach's assessment match Stockfish's?

Grades the coarse verdict (``winning`` … ``losing``) the coach assigns a position
against the golden's stored bucket, which was derived from the pinned engine
score. Exact by default; an optional ``tolerance`` accepts answers within N
adjacent buckets (e.g. ``better`` for ``winning``) for a softer grade.
"""

from __future__ import annotations

from evals.data.schema import ChessGolden
from evals.harness.checkers import BUCKETS, bucket_distance
from evals.harness.task import CoachResult
from evals.metrics._base import DeterministicMetric


class EvalBucketMetric(DeterministicMetric):  # type: ignore[no-untyped-call]
    """1.0 iff the coach's bucket matches (within ``tolerance``) the expected one."""

    def __init__(self, threshold: float = 1.0, *, tolerance: int = 0) -> None:
        super().__init__(threshold)
        self.tolerance = tolerance

    def _evaluate(self, golden: ChessGolden, result: CoachResult) -> tuple[float, str]:
        expected = golden.expected_bucket
        answer = result.eval_bucket
        if not answer:
            return 0.0, "coach produced no bucket"
        if answer not in BUCKETS:
            return 0.0, f"unknown bucket {answer!r}"
        assert expected is not None  # guaranteed by the schema for eval_bucket
        distance = bucket_distance(answer, expected)
        if distance <= self.tolerance:
            note = "" if distance == 0 else f" (within tolerance {self.tolerance})"
            return 1.0, f"{answer} vs expected {expected}{note}"
        return 0.0, f"{answer} vs expected {expected}, {distance} buckets off"

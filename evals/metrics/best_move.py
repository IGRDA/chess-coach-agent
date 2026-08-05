"""Best-move metric: did the coach play a move in the accepted set?

The purest exact-match grade. The coach's move and every accepted solution are
normalised to canonical UCI in the golden's position (so SAN and UCI compare
correctly), and the answer scores 1.0 iff it lands in that set. An illegal or
missing move scores 0.0 — it can never accidentally match.
"""

from __future__ import annotations

from evals.data.schema import ChessGolden
from evals.harness.checkers import normalize_move
from evals.harness.task import CoachResult
from evals.metrics._base import DeterministicMetric


class BestMoveMetric(DeterministicMetric):  # type: ignore[no-untyped-call]
    """1.0 iff the coach's move equals an accepted solution move."""

    def _evaluate(self, golden: ChessGolden, result: CoachResult) -> tuple[float, str]:
        assert golden.fen is not None  # guaranteed by schema for best_move
        if not result.best_move:
            return 0.0, "coach produced no move"
        try:
            played = normalize_move(golden.fen, result.best_move)
        except ValueError:
            return 0.0, f"illegal move {result.best_move!r}"
        accepted = {normalize_move(golden.fen, m) for m in golden.solution_moves}
        if played in accepted:
            return 1.0, f"played {played}, in accepted {sorted(accepted)}"
        return 0.0, f"played {played}, expected one of {sorted(accepted)}"

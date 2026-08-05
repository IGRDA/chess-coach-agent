"""Endgame-technique metric: right key move *and* right result.

Endgame technique is only demonstrated when both halves agree with the book: the
coach must play a key move from the accepted set and correctly claim the outcome
(win/draw/loss). Each half is worth half the score, so a partly-right answer is
visible in reports, while the default 1.0 threshold still requires both.
"""

from __future__ import annotations

from evals.data.schema import ChessGolden
from evals.harness.checkers import normalize_move
from evals.harness.task import CoachResult
from evals.metrics._base import DeterministicMetric


class EndgameTechniqueMetric(DeterministicMetric):  # type: ignore[no-untyped-call]
    """Half credit for the key move, half for the claimed result."""

    def _evaluate(self, golden: ChessGolden, result: CoachResult) -> tuple[float, str]:
        assert golden.fen is not None  # guaranteed by schema for endgame
        move_ok, move_note = self._move_ok(golden, result)
        result_ok = result.result == golden.expected_result
        result_note = (
            f"result {result.result} == {golden.expected_result}"
            if result_ok
            else f"result {result.result} != expected {golden.expected_result}"
        )
        score = 0.5 * move_ok + 0.5 * result_ok
        return score, f"{move_note}; {result_note}"

    def _move_ok(self, golden: ChessGolden, result: CoachResult) -> tuple[bool, str]:
        assert golden.fen is not None  # guaranteed by schema for endgame
        if not result.best_move:
            return False, "no key move"
        try:
            played = normalize_move(golden.fen, result.best_move)
        except ValueError:
            return False, f"illegal key move {result.best_move!r}"
        accepted = {normalize_move(golden.fen, m) for m in golden.solution_moves}
        if played in accepted:
            return True, f"key move {played} accepted"
        return False, f"key move {played} not in {sorted(accepted)}"

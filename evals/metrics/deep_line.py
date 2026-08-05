"""Deep-line metric: did the coach calculate the main continuation?

Unlike the best-move metric, this grades a short line of best play: the side to
move's candidate, the opponent's reply, and the continuation. The first move is
worth half the score because it is the candidate the coach recommends; the rest
of the line shares the other half so partial calculation is visible in reports
while the default threshold still requires the whole line.
"""

from __future__ import annotations

import chess

from evals.data.schema import ChessGolden
from evals.harness.checkers import normalize_move
from evals.harness.task import CoachResult
from evals.metrics._base import DeterministicMetric


class DeepLineMetric(DeterministicMetric):  # type: ignore[no-untyped-call]
    """1.0 iff the coach's continuation matches the expected line."""

    def _evaluate(self, golden: ChessGolden, result: CoachResult) -> tuple[float, str]:
        if golden.fen is None:
            return 0.0, "deep_line golden has no FEN"
        expected = _normalize_line(golden.fen, golden.expected_line)
        answer = result.line or ([result.best_move] if result.best_move else [])
        if not answer:
            return 0.0, "coach produced no line"

        try:
            played = _normalize_line(golden.fen, answer)
        except ValueError as exc:
            return 0.0, f"illegal line: {exc}"

        matched = 0
        for got, want in zip(played, expected, strict=False):
            if got != want:
                break
            matched += 1

        if matched == len(expected) and len(played) == len(expected):
            return 1.0, f"line matched: {' '.join(expected)}"
        if matched == 0:
            return 0.0, f"first move {played[0]} != expected {expected[0]}"

        score = 0.5
        if len(expected) > 1:
            score += 0.5 * ((matched - 1) / (len(expected) - 1))
        return (
            score,
            f"matched {matched}/{len(expected)} moves; played {' '.join(played)}; "
            f"expected {' '.join(expected)}",
        )


def _normalize_line(fen: str, moves: list[str]) -> list[str]:
    """Normalize a SAN/UCI move sequence to UCI, validating each ply in order."""
    board = chess.Board(fen)
    normalized: list[str] = []
    for move in moves:
        uci = normalize_move(board.fen(), move)
        normalized.append(uci)
        board.push(chess.Move.from_uci(uci))
    return normalized

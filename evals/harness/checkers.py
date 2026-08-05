"""Pure position checkers and the evaluation-bucket scale.

Network-free, engine-free helpers built on python-chess that the whole framework
leans on: FEN legality, move legality/normalisation (so a coach's SAN and a
golden's UCI compare correctly), and the mapping from a centipawn/mate score to a
coarse human bucket (``winning`` … ``losing``). Centralising the bucket scale
here keeps the oracle, the metrics and the dataset validator using one
definition.
"""

from __future__ import annotations

from typing import Literal, get_args

import chess

Bucket = Literal["losing", "worse", "equal", "better", "winning"]
"""Coarse, human-facing assessment of a position from the side-to-move POV."""

BUCKETS: tuple[Bucket, ...] = get_args(Bucket)
"""The buckets, worst → best; index order defines adjacency for tolerance."""

# Centipawn thresholds (side-to-move POV). Symmetric about zero so that a
# position and its mirror land in mirror buckets.
_BETTER_CP = 100
_WINNING_CP = 300


def is_valid_fen(fen: str) -> bool:
    """Return whether ``fen`` parses to a legal, well-formed position."""
    try:
        board = chess.Board(fen)
    except ValueError:
        return False
    return board.is_valid()


def to_board(fen: str) -> chess.Board:
    """Parse ``fen`` into a validated board, or raise ``ValueError``."""
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError(f"illegal position: {fen!r}")
    return board


def normalize_move(fen: str, move: str) -> str:
    """Normalise a SAN or UCI move to canonical UCI in the given position.

    Raises ``ValueError`` if the move is unparseable or illegal in ``fen`` — the
    metrics rely on this so an illegal answer can never accidentally match.
    """
    board = to_board(fen)
    parsed: chess.Move | None = None
    try:
        parsed = board.parse_san(move)
    except (ValueError, AssertionError):
        try:
            candidate = chess.Move.from_uci(move)
        except ValueError:
            parsed = None
        else:
            if candidate in board.legal_moves:
                parsed = candidate
    if parsed is None:
        raise ValueError(f"illegal or unparseable move {move!r} in {fen!r}")
    return parsed.uci()


def is_legal_move(fen: str, move: str) -> bool:
    """Return whether ``move`` (SAN or UCI) is legal in ``fen``."""
    try:
        normalize_move(fen, move)
    except ValueError:
        return False
    return True


def bucket_from_score(cp: int | None, mate: int | None) -> Bucket:
    """Map a Stockfish score (side-to-move POV) to a :data:`Bucket`.

    Exactly one of ``cp`` (centipawns) or ``mate`` (moves to mate, signed) is
    expected; a forced mate dominates any centipawn reading.
    """
    if mate is not None:
        return "winning" if mate > 0 else "losing"
    if cp is None:
        raise ValueError("either cp or mate must be provided")
    if cp >= _WINNING_CP:
        return "winning"
    if cp >= _BETTER_CP:
        return "better"
    if cp <= -_WINNING_CP:
        return "losing"
    if cp <= -_BETTER_CP:
        return "worse"
    return "equal"


def bucket_distance(a: str, b: str) -> int:
    """Number of steps between two buckets on the scale (0 == identical).

    Raises ``ValueError`` for anything outside :data:`BUCKETS`.
    """
    try:
        return abs(BUCKETS.index(a) - BUCKETS.index(b))
    except ValueError as exc:
        raise ValueError(f"unknown bucket in {(a, b)!r}") from exc

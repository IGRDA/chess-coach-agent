"""Syzygy endgame tablebases: exact truth for the simplest positions, when present.

For positions with seven pieces or fewer, a Syzygy tablebase gives the *provably*
correct result — win, draw, or loss — and the distance to a pawn move or capture that
makes progress. That is stronger than any engine search, and it is the right authority
for endgame coaching.

Tablebases are large files, so they are optional. :class:`Tablebase` degrades
gracefully: with no directory configured, too many pieces, or a table simply absent,
:meth:`probe` returns ``available=False`` instead of raising. Point it at a directory
of ``.rtbw``/``.rtbz`` files with the ``CHESS_COACH_SYZYGY_PATH`` environment variable
(or the ``syzygy_path`` setting) to switch it on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import chess
import chess.syzygy

_MAX_PIECES = 7


@dataclass(frozen=True)
class TablebaseResult:
    """A tablebase verdict, or ``available=False`` when no table could answer."""

    available: bool
    wdl: str | None = None  # win | draw | loss, from the side to move
    dtz: int | None = None  # distance to zeroing (pawn move or capture)
    best_moves: tuple[str, ...] = ()  # UCI moves that preserve the result


def _wdl_word(wdl: int) -> str:
    """Collapse Syzygy's five WDL values (incl. cursed/blessed) to win/draw/loss."""
    if wdl > 0:
        return "win"
    if wdl < 0:
        return "loss"
    return "draw"


class Tablebase:
    """An optional Syzygy probe. Construct once; :meth:`probe` is always safe."""

    def __init__(self, path: str | None = None) -> None:
        self._path = path or os.environ.get("CHESS_COACH_SYZYGY_PATH") or None

    @property
    def configured(self) -> bool:
        return self._path is not None

    def probe(self, fen: str) -> TablebaseResult:
        board = chess.Board(fen)
        if not board.is_valid():
            raise ValueError(f"illegal position: {fen!r}")
        if self._path is None or chess.popcount(board.occupied) > _MAX_PIECES:
            return TablebaseResult(available=False)
        try:
            with chess.syzygy.open_tablebase(self._path) as tables:
                wdl = tables.probe_wdl(board)
                dtz = tables.probe_dtz(board)
                best = self._preserving_moves(board, tables, wdl)
        except (KeyError, chess.syzygy.MissingTableError, OSError, ValueError):
            return TablebaseResult(available=False)
        return TablebaseResult(
            available=True, wdl=_wdl_word(wdl), dtz=dtz, best_moves=best
        )

    @staticmethod
    def _preserving_moves(
        board: chess.Board, tables: chess.syzygy.Tablebase, root_wdl: int
    ) -> tuple[str, ...]:
        """Legal moves whose position keeps the same win/draw/loss result."""
        keep: list[str] = []
        for move in board.legal_moves:
            board.push(move)
            try:
                child = -tables.probe_wdl(board)
            except (KeyError, chess.syzygy.MissingTableError):
                child = None
            board.pop()
            if child is not None and _wdl_word(child) == _wdl_word(root_wdl):
                keep.append(move.uci())
        return tuple(keep)

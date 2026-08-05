"""BoardState: the editable, playable board model behind the TUI.

A deep little module over ``python-chess`` that holds the two ways the board
changes in the app and keeps their invariants straight:

* **Editing** — stamping a piece on a square, erasing one, or setting the
  side-to-move / castling / en-passant fields. Editing redefines the position, so
  it *rebases* the variation: the current board becomes the new origin and any
  played line is dropped (a half-played line has no meaning once you rearrange the
  pieces).
* **Playing** — pushing a legal move (SAN or UCI), which extends the variation the
  bottom bar shows; :meth:`undo` takes the last one back down to the origin.

Everything is string-in / string-out (squares like ``"e4"``, pieces like ``"P"``,
FENs, SAN) so the Textual widgets never touch ``chess`` types. Move legality and
position validity are answered here; the coach adapter still has the final say on
whether a FEN is coachable.
"""

from __future__ import annotations

import chess

STARTING_FEN = chess.STARTING_FEN

_COLORS: dict[str, chess.Color] = {
    "white": chess.WHITE,
    "w": chess.WHITE,
    "black": chess.BLACK,
    "b": chess.BLACK,
}


class IllegalMove(ValueError):
    """Raised when a move is not legal in the current position."""


class BoardState:
    """The current position, the line played into it, and the view orientation."""

    def __init__(self, fen: str = STARTING_FEN) -> None:
        self._board = chess.Board(fen)
        self._root = self._board.copy()
        self._orientation: chess.Color = chess.WHITE

    # -- editing: redefines the position and rebases the variation to it --------

    def set_piece(self, square: str, piece: str) -> None:
        """Stamp ``piece`` (e.g. ``"P"``, ``"n"``) onto ``square`` (e.g. ``"e4"``)."""
        board = self._editable()
        board.set_piece_at(chess.parse_square(square), chess.Piece.from_symbol(piece))
        self._rebase(board)

    def remove_piece(self, square: str) -> None:
        """Erase whatever occupies ``square``; a no-op if it is already empty."""
        board = self._editable()
        board.remove_piece_at(chess.parse_square(square))
        self._rebase(board)

    def set_turn(self, color: str) -> None:
        """Set the side to move (``"white"``/``"black"`` or ``"w"``/``"b"``)."""
        board = self._editable()
        board.turn = _COLORS[color.lower()]
        self._rebase(board)

    def set_castling(self, rights: str) -> None:
        """Set the castling-rights field from a FEN fragment (e.g. ``"KQkq"``)."""
        board = self._editable()
        board.set_castling_fen(rights or "-")
        self._rebase(board)

    def set_en_passant(self, square: str | None) -> None:
        """Set (or clear, with ``None``) the en-passant target square."""
        board = self._editable()
        board.ep_square = chess.parse_square(square) if square else None
        self._rebase(board)

    def clear(self) -> None:
        """Empty the board for from-scratch setup (invalid until kings are placed)."""
        self._rebase(chess.Board(None))

    def reset(self) -> None:
        """Return to the standard starting position and drop the line."""
        self._rebase(chess.Board())

    # -- playing ---------------------------------------------------------------

    def play(self, move: str) -> str:
        """Play ``move`` (UCI or SAN) and return its UCI; raise on an illegal one."""
        parsed = self._parse_move(move)
        self._board.push(parsed)
        return parsed.uci()

    def undo(self) -> str | None:
        """Take back the last played move; return its UCI, or ``None`` at the root."""
        if not self._board.move_stack:
            return None
        return self._board.pop().uci()

    # -- view ------------------------------------------------------------------

    def fen(self) -> str:
        return self._board.fen()

    def is_valid(self) -> bool:
        return self._board.is_valid()

    def flip(self) -> None:
        self._orientation = not self._orientation

    @property
    def orientation(self) -> str:
        return "white" if self._orientation == chess.WHITE else "black"

    @property
    def turn(self) -> str:
        return "white" if self._board.turn == chess.WHITE else "black"

    def piece_symbol_at(self, square: str) -> str | None:
        """The piece symbol on ``square`` (``"P"``, ``"k"``, …), or ``None``."""
        piece = self._board.piece_at(chess.parse_square(square))
        return piece.symbol() if piece else None

    def last_move_uci(self) -> str | None:
        """The last played move in UCI, or ``None`` if the line is empty."""
        stack = self._board.move_stack
        return stack[-1].uci() if stack else None

    def variation_san(self) -> str:
        """The played line as SAN with move numbers, e.g. ``"1. Nf3 d5 2. g3"``."""
        if not self._board.move_stack:
            return ""
        return self._root.variation_san(self._board.move_stack)

    # -- internals -------------------------------------------------------------

    def _editable(self) -> chess.Board:
        """A fresh board at the current position with no move history to edit on."""
        return chess.Board(self._board.fen())

    def _rebase(self, board: chess.Board) -> None:
        self._board = board
        self._root = board.copy()

    def _parse_move(self, move: str) -> chess.Move:
        text = move.strip()
        try:
            uci = chess.Move.from_uci(text)
        except ValueError:
            uci = None
        if uci is not None and uci in self._board.legal_moves:
            return uci
        try:
            return self._board.parse_san(text)
        except ValueError as exc:
            raise IllegalMove(f"illegal move: {move!r}") from exc

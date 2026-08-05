"""Pure view helpers for the board widget and bottom bar.

Square ordering for the two orientations, piece-symbol → unicode glyph, light/dark
square colouring, and the short eval/variation strings. No Textual and no engine —
the widgets call these so the drawing stays testable and consistent.
"""

from __future__ import annotations

import chess

_FILES = "abcdefgh"

# Solid, filled figurines for *every* piece, keyed by type. The stock unicode
# symbols draw white pieces as hollow outlines and black pieces as filled shapes,
# which fights the colour coding and reads faintly on a terminal. We instead draw
# every piece with the dense filled glyph and let the text colour alone say whose
# it is — the standard, legible "figurine on a coloured square" look.
_SOLID_GLYPHS: dict[str, str] = {
    "k": "♚",  # ♚
    "q": "♛",  # ♛
    "r": "♜",  # ♜
    "b": "♝",  # ♝
    "n": "♞",  # ♞
    "p": "♟",  # ♟
}


def ordered_rows(orientation: str) -> list[list[str]]:
    """Square names grouped into display rows, top row first.

    White orientation shows rank 8 at the top and file ``a`` on the left; black
    orientation mirrors both axes.
    """
    ranks = range(8, 0, -1)
    files = _FILES
    if orientation == "black":
        ranks = range(1, 9)
        files = _FILES[::-1]
    return [[f"{f}{r}" for f in files] for r in ranks]


def file_labels(orientation: str) -> list[str]:
    """File labels in display order, left to right for the current orientation."""
    return list(_FILES[::-1] if orientation == "black" else _FILES)


def rank_labels(orientation: str) -> list[str]:
    """Rank labels in display order, top to bottom for the current orientation."""
    ranks = range(1, 9) if orientation == "black" else range(8, 0, -1)
    return [str(rank) for rank in ranks]


def piece_glyph(symbol: str | None) -> str:
    """The dense, filled glyph for a piece symbol (``"P"``, ``"k"``…), or a space.

    Both colours use the same filled figurine; the caller distinguishes white from
    black by colour (see :func:`piece_is_white`). Used by the piece *palette*, where a
    coloured band already says whose piece it is.
    """
    if not symbol:
        return " "
    return _SOLID_GLYPHS[symbol.lower()]


def board_piece_glyph(symbol: str | None) -> str:
    """The glyph a piece draws with *on the board*, or a space when empty.

    Unlike the palette, the board draws White with the light, open figurines
    (``♔♕♖``) and Black with the solid ones (``♚♛♜``) — the familiar look where a
    white piece reads as white and a black piece reads as filled.
    """
    if not symbol:
        return " "
    return chess.Piece.from_symbol(symbol).unicode_symbol()


def piece_is_white(symbol: str) -> bool:
    """Whether a piece symbol denotes a white piece (uppercase)."""
    return symbol.isupper()


def square_is_light(square: str) -> bool:
    """Whether ``square`` is a light square (a1 is dark, h1 is light)."""
    index = chess.parse_square(square)
    return (chess.square_file(index) + chess.square_rank(index)) % 2 == 1


def format_eval(eval_bucket: str | None, *, revealed: bool) -> str:
    """The bottom-bar evaluation text: hidden until revealed, then the bucket."""
    if not revealed:
        return "hidden"
    return eval_bucket or "—"


def format_variation(san: str) -> str:
    """The variation line, or a dash when no moves have been played."""
    return san or "—"

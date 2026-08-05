"""Rendering tests: the pure view helpers the board widget draws with.

Square order under either orientation, piece glyphs, light/dark colouring, and the
bottom-bar eval/variation strings. Strings in, strings out — no Textual.
"""

from __future__ import annotations

from chess_coach.interface.tui import rendering


def test_white_orientation_runs_rank_8_down_to_1() -> None:
    rows = rendering.ordered_rows("white")

    assert rows[0] == ["a8", "b8", "c8", "d8", "e8", "f8", "g8", "h8"]
    assert rows[-1] == ["a1", "b1", "c1", "d1", "e1", "f1", "g1", "h1"]


def test_black_orientation_mirrors_the_board() -> None:
    rows = rendering.ordered_rows("black")

    assert rows[0] == ["h1", "g1", "f1", "e1", "d1", "c1", "b1", "a1"]
    assert rows[-1] == ["h8", "g8", "f8", "e8", "d8", "c8", "b8", "a8"]


def test_coordinate_labels_follow_orientation() -> None:
    assert rendering.file_labels("white") == list("abcdefgh")
    assert rendering.rank_labels("white") == list("87654321")

    assert rendering.file_labels("black") == list("hgfedcba")
    assert rendering.rank_labels("black") == list("12345678")


def test_palette_glyphs_are_dense_filled_for_both_colours() -> None:
    # The palette shares one filled figurine per piece; the coloured band tells the
    # sides apart, so a white pawn draws with the solid glyph, same as a black pawn.
    assert rendering.piece_glyph("P") == "♟"  # white pawn, filled
    assert rendering.piece_glyph("p") == "♟"  # black pawn, same shape
    assert rendering.piece_glyph("K") == "♚"  # white king, filled
    assert rendering.piece_glyph("k") == "♚"  # black king, same shape
    assert rendering.piece_glyph(None) == " "


def test_board_glyphs_draw_white_open_and_black_solid() -> None:
    # On the board White keeps the light, open figurines and Black the solid ones.
    assert rendering.board_piece_glyph("P") == "♙"  # white pawn, open
    assert rendering.board_piece_glyph("p") == "♟"  # black pawn, solid
    assert rendering.board_piece_glyph("K") == "♔"  # white king, open
    assert rendering.board_piece_glyph("k") == "♚"  # black king, solid
    assert rendering.board_piece_glyph(None) == " "


def test_piece_colour_follows_symbol_case() -> None:
    assert rendering.piece_is_white("Q") is True
    assert rendering.piece_is_white("q") is False


def test_square_colour_follows_the_chessboard() -> None:
    assert rendering.square_is_light("a1") is False
    assert rendering.square_is_light("h1") is True
    assert rendering.square_is_light("e4") is True
    assert rendering.square_is_light("d4") is False


def test_eval_stays_hidden_until_revealed() -> None:
    assert rendering.format_eval("equal", revealed=False) == "hidden"
    assert rendering.format_eval("equal", revealed=True) == "equal"
    assert rendering.format_eval(None, revealed=True) == "—"


def test_variation_line_shows_a_dash_when_empty() -> None:
    assert rendering.format_variation("") == "—"
    assert rendering.format_variation("1. e4 e5") == "1. e4 e5"

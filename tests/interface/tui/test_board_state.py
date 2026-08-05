"""BoardState tests: the pure editable + playable board behind the TUI.

Exercises the two ways the board changes — free editing (stamping pieces, setting
side-to-move / castling / en-passant) and playing legal moves that build a
variation — plus validity, undo, reset and flip. No Textual, no engine: pure
python-chess bookkeeping, so the widget layer can stay a thin shell over it.
"""

from __future__ import annotations

import chess
import pytest

from chess_coach.interface.tui.board_state import BoardState, IllegalMove

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_starts_from_the_standard_position() -> None:
    board = BoardState()

    assert board.fen() == START_FEN
    assert board.is_valid()
    assert board.turn == "white"
    assert board.variation_san() == ""


def test_stamping_a_piece_shows_in_the_fen() -> None:
    board = BoardState()
    board.clear()

    board.set_piece("e4", "P")

    assert board.piece_symbol_at("e4") == "P"
    assert board.fen().split()[0] == "8/8/8/8/4P3/8/8/8"


def test_erasing_a_piece_empties_the_square() -> None:
    board = BoardState()

    board.remove_piece("e2")

    assert board.piece_symbol_at("e2") is None


def test_setting_side_to_move_and_castling() -> None:
    board = BoardState()

    board.set_turn("black")
    board.set_castling("Kq")

    fields = board.fen().split()
    assert fields[1] == "b"
    assert fields[2] == "Kq"


def test_en_passant_target_can_be_set_and_cleared() -> None:
    # Black pawn on c4, White to have just played d2-d4: d3 is a real e.p. target.
    fen = "rnbqkbnr/pp1ppppp/8/8/2pP4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 3"
    board = BoardState(fen)
    assert board.fen().split()[3] == "-"

    board.set_en_passant("d3")
    assert board.fen().split()[3] == "d3"

    board.set_en_passant(None)
    assert board.fen().split()[3] == "-"


def test_empty_board_is_invalid_until_kings_are_placed() -> None:
    board = BoardState()
    board.clear()
    assert not board.is_valid()

    board.set_piece("e1", "K")
    board.set_piece("e8", "k")

    assert board.is_valid()


def test_playing_legal_moves_builds_the_variation() -> None:
    board = BoardState()

    board.play("Nf3")
    board.play("d5")
    board.play("g3")

    assert board.variation_san() == "1. Nf3 d5 2. g3"
    assert board.last_move_uci() == "g2g3"


def test_accepts_uci_moves_too() -> None:
    board = BoardState()

    board.play("e2e4")

    assert board.last_move_uci() == "e2e4"
    assert board.variation_san() == "1. e4"


def test_illegal_move_is_rejected_and_leaves_board_unchanged() -> None:
    board = BoardState()
    before = board.fen()

    with pytest.raises(IllegalMove):
        board.play("e2e5")

    assert board.fen() == before
    assert board.variation_san() == ""


def test_undo_takes_back_the_last_move() -> None:
    board = BoardState()
    board.play("e2e4")
    board.play("e7e5")

    board.undo()

    assert board.variation_san() == "1. e4"
    assert board.last_move_uci() == "e2e4"


def test_undo_on_the_root_position_is_a_no_op() -> None:
    board = BoardState()

    assert board.undo() is None
    assert board.fen() == START_FEN


def test_reset_returns_to_the_starting_position() -> None:
    board = BoardState()
    board.play("e2e4")

    board.reset()

    assert board.fen() == START_FEN
    assert board.variation_san() == ""


def test_editing_rebases_the_variation_to_the_edited_position() -> None:
    board = BoardState()
    board.play("e2e4")

    # Stamping a piece redefines the position; the old line no longer applies.
    board.set_piece("h4", "Q")

    assert board.variation_san() == ""
    assert board.piece_symbol_at("h4") == "Q"
    assert board.piece_symbol_at("e4") == "P"  # the played pawn stays put


def test_flip_toggles_orientation_without_changing_the_position() -> None:
    board = BoardState()
    assert board.orientation == "white"

    board.flip()

    assert board.orientation == "black"
    assert board.fen() == START_FEN


def test_squares_iterates_in_the_chess_module_order() -> None:
    # Sanity that a caller can enumerate the board for rendering.
    board = BoardState()
    assert board.piece_symbol_at("a1") == "R"
    assert board.piece_symbol_at(chess.square_name(chess.E8)) == "k"

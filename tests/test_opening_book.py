"""Opening book: naming, book moves, transposition, and out-of-book behavior."""

from __future__ import annotations

import chess
import pytest

from chess_coach.adapters.coach.opening_book import OpeningBook, position_key


def _fen_after(*sans: str) -> str:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board.fen()


def test_names_a_known_opening() -> None:
    book = OpeningBook()
    info = book.lookup(
        _fen_after("e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6")
    )
    assert info.is_known()
    assert info.name == "Sicilian Najdorf"
    assert info.eco == "B90"


def test_start_position_offers_main_first_moves() -> None:
    book = OpeningBook()
    info = book.lookup(chess.STARTING_FEN)
    sans = {m.san for m in info.book_moves}
    assert {"e4", "d4", "c4", "Nf3"} <= sans


def test_transposition_is_recognized() -> None:
    """1.e4 c5 2.Nc3 and 1.Nc3 c5 2.e4 reach the same position and lookup."""
    book = OpeningBook()
    a = book.lookup(_fen_after("e4", "c5", "Nc3"))
    b = book.lookup(_fen_after("Nc3", "c5", "e4"))
    assert a.name and a.name == b.name


def test_out_of_book_position_is_unknown() -> None:
    book = OpeningBook()
    # A tactics golden position, nowhere in opening theory.
    info = book.lookup("6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1")
    assert not info.is_known()
    assert info.book_moves == []


def test_illegal_fen_raises() -> None:
    with pytest.raises(ValueError):
        OpeningBook().lookup("not-a-fen")


def test_position_key_ignores_move_clocks() -> None:
    board = chess.Board()
    a = position_key(board)
    board.halfmove_clock = 7
    board.fullmove_number = 12
    assert position_key(board) == a

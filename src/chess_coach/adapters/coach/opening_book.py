"""Offline opening database: name a position and suggest its book moves.

A small, self-contained opening book the coach consults before reaching for the
engine — because in the opening the *right* move is a matter of established
theory, not a fresh search, and naming the opening ("this is the Najdorf
Sicilian") is itself part of good coaching. It is deliberately engine-free and
network-free: a curated set of mainline theory, replayed once at import through
python-chess so every stored position is legal by construction, then indexed by
position for O(1) lookup.

Design
    The book is authored as human-readable SAN lines (:data:`_LINES`); the index
    is derived from them. Keying on a position — not a move sequence — means a
    FEN that *transposes* into a known line is still recognised. Each indexed
    position remembers the theory moves played from it and the deepest opening
    name that runs through it.

Optionally, if ``$OPENING_BOOK_PATH`` points at a Polyglot ``.bin`` book, that
book's weighted moves are offered too (see :meth:`OpeningBook.polyglot_moves`),
so a richer database can be dropped in without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

import chess
import chess.polyglot


@dataclass(frozen=True)
class BookMove:
    """One theory move available from a position."""

    san: str
    uci: str
    opening: str
    eco: str


@dataclass(frozen=True)
class OpeningInfo:
    """What the book knows about a position that appears in its lines."""

    name: str
    eco: str
    book_moves: list[BookMove] = field(default_factory=list)

    def is_known(self) -> bool:
        return bool(self.name)


# Mainline opening theory, in SAN. Each entry is (ECO, name, moves). The moves are
# replayed through python-chess at import, so an illegal line fails loudly here
# rather than silently corrupting the index. Kept intentionally shallow and broad:
# enough to recognise the major openings and offer their principled first moves.
_LINES: tuple[tuple[str, str, str], ...] = (
    ("C60", "Ruy Lopez", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6"),
    ("C50", "Italian Game", "e4 e5 Nf3 Nc6 Bc4 Bc5"),
    ("C44", "Scotch Game", "e4 e5 Nf3 Nc6 d4 exd4 Nxd4"),
    ("C25", "Vienna Game", "e4 e5 Nc3 Nf6"),
    ("C30", "King's Gambit", "e4 e5 f4"),
    ("C42", "Petrov Defense", "e4 e5 Nf3 Nf6"),
    ("B20", "Sicilian Defense", "e4 c5"),
    ("B90", "Sicilian Najdorf", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6"),
    ("B33", "Sicilian Sveshnikov", "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5"),
    ("B23", "Sicilian Closed", "e4 c5 Nc3 Nc6 g3"),
    ("C00", "French Defense", "e4 e6 d4 d5"),
    ("C02", "French Advance", "e4 e6 d4 d5 e5"),
    ("B10", "Caro-Kann Defense", "e4 c6 d4 d5"),
    ("B01", "Scandinavian Defense", "e4 d5 exd5 Qxd5 Nc3 Qa5"),
    ("B07", "Pirc Defense", "e4 d6 d4 Nf6 Nc3 g6"),
    ("B00", "Modern Defense", "e4 g6 d4 Bg7"),
    ("D06", "Queen's Gambit", "d4 d5 c4"),
    ("D30", "Queen's Gambit Declined", "d4 d5 c4 e6 Nc3 Nf6"),
    ("D20", "Queen's Gambit Accepted", "d4 d5 c4 dxc4"),
    ("D10", "Slav Defense", "d4 d5 c4 c6"),
    ("D02", "London System", "d4 d5 Nf3 Nf6 Bf4"),
    ("E60", "King's Indian Defense", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6"),
    ("E20", "Nimzo-Indian Defense", "d4 Nf6 c4 e6 Nc3 Bb4"),
    ("E12", "Queen's Indian Defense", "d4 Nf6 c4 e6 Nf3 b6"),
    ("A56", "Benoni Defense", "d4 Nf6 c4 c5 d5 e6"),
    ("D80", "Grünfeld Defense", "d4 Nf6 c4 g6 Nc3 d5"),
    ("A45", "Trompowsky Attack", "d4 Nf6 Bg5"),
    ("A10", "English Opening", "c4 e5 Nc3 Nf6"),
    ("A04", "Réti Opening", "Nf3 d5 c4"),
    ("A80", "Dutch Defense", "d4 f5"),
)


def position_key(board: chess.Board) -> str:
    """Canonical position key: placement, side, castling, en-passant target.

    Drops the halfmove/fullmove clocks so two routes into the same position
    (a transposition) share a key. This is the FEN's first four fields.
    """
    return " ".join(board.fen().split()[:4])


@lru_cache(maxsize=1)
def _index() -> dict[str, OpeningInfo]:
    """Build the position → :class:`OpeningInfo` index from :data:`_LINES`.

    Cached so the (cheap) replay happens once per process. Deeper lines overwrite
    the opening *name* of a shared position with the more specific variation, so a
    transposition reports the most informative label.
    """
    moves_by_pos: dict[str, dict[str, BookMove]] = {}
    name_by_pos: dict[str, tuple[str, str, int]] = {}

    for eco, name, san_line in _LINES:
        board = chess.Board()
        for ply, san in enumerate(san_line.split()):
            move = board.parse_san(san)
            key = position_key(board)
            slot = moves_by_pos.setdefault(key, {})
            slot.setdefault(
                move.uci(),
                BookMove(san=board.san(move), uci=move.uci(), opening=name, eco=eco),
            )
            board.push(move)
            # Label the position *after* the move with the line it belongs to;
            # a deeper ply wins so specific variations beat their parent.
            after = position_key(board)
            prior = name_by_pos.get(after)
            if prior is None or ply + 1 > prior[2]:
                name_by_pos[after] = (name, eco, ply + 1)

    index: dict[str, OpeningInfo] = {}
    for key in set(moves_by_pos) | set(name_by_pos):
        name, eco, _ = name_by_pos.get(key, ("", "", 0))
        book_moves = sorted(moves_by_pos.get(key, {}).values(), key=lambda m: m.san)
        index[key] = OpeningInfo(name=name, eco=eco, book_moves=book_moves)
    return index


class OpeningBook:
    """Look positions up in the bundled theory (and an optional Polyglot book).

    Deep, tiny interface: :meth:`lookup` turns a FEN into what theory knows —
    the opening's name/ECO and the book moves available — or a clear "out of
    book" result. All the replay and indexing detail stays hidden.
    """

    def __init__(self, polyglot_path: str | None = None) -> None:
        self._polyglot_path = polyglot_path or os.environ.get("OPENING_BOOK_PATH")

    def lookup(self, fen: str) -> OpeningInfo:
        """Return theory for ``fen`` (name/ECO + book moves), or an empty info.

        Raises ``ValueError`` if ``fen`` is not a legal position.
        """
        board = chess.Board(fen)
        if not board.is_valid():
            raise ValueError(f"illegal position: {fen!r}")
        info = _index().get(position_key(board))
        if info is not None:
            return info
        # Not in the curated lines; fall back to a Polyglot book if configured.
        poly = self.polyglot_moves(board)
        if poly:
            return OpeningInfo(name="", eco="", book_moves=poly)
        return OpeningInfo(name="", eco="", book_moves=[])

    def polyglot_moves(self, board: chess.Board) -> list[BookMove]:
        """Book moves for ``board`` from the optional Polyglot ``.bin``, if any."""
        if not self._polyglot_path or not os.path.exists(self._polyglot_path):
            return []
        moves: list[BookMove] = []
        try:
            with chess.polyglot.open_reader(self._polyglot_path) as reader:
                for entry in reader.find_all(board):
                    move = entry.move
                    moves.append(
                        BookMove(
                            san=board.san(move),
                            uci=move.uci(),
                            opening="polyglot",
                            eco="",
                        )
                    )
        except (OSError, ValueError):
            return []
        return moves

"""Reconstruct the annotated games printed in a chess book's PDF text layer.

Pure extraction: PDF in, verified games out. No engine, no network, no grading —
those belong to the caller (:mod:`evals.tools.book_move_goldens`), which turns
these positions into graded problems.

Three obstacles stand between the printed page and a list of moves, and each is
solved by exploiting something the layout preserves rather than by guessing:

* **The figurine glyphs are mangled.** The PDF's font encoding turns a knight into
  'lD', 'tLl', 'li:J', … and collapses several pieces onto U+FFFD. Rather than
  reverse-engineer the encoding we discard the glyph and recover the piece by
  *legality*: the destination square survives intact, so python-chess is asked
  which piece could have played the move. :func:`classify` narrows the candidates
  when the glyph is legible, because legality alone is often ambiguous (both Nf3
  and Qf3 are legal after 1.e4 e5).
* **Analysis variations look exactly like game moves.** The book quotes lines such
  as "If Black tries 6 ... exd4" inside its prose, with real move numbers. The
  game's own moves are *centred* on the page while the notes are left-aligned, so
  reading in ``layout`` mode and keeping only the deeply-indented lines separates
  the two.
* **The page is two columns.** Layout mode preserves horizontal position, so each
  physical line holds a slice of both columns; :func:`_columns` cuts every line and
  emits the left halves before the right, restoring true reading order.

Correctness is self-enforcing. Every move is replayed through python-chess and a
game is *truncated* at the first token that does not resolve to exactly one legal
move, so a misread never propagates into a wrong position. Short games are the
price; wrong FENs are not paid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import chess

PIECES = ("N", "B", "R", "Q", "K")

# Where the right column starts in the layout-mode rendering of a page.
SPLIT_COL = 50

# The ellipsis marking a Black move survives as '...', '•••' or spaced '.. .'.
_ELLIPSIS = r"[.•]\s*[.•]\s*[.•]"
# A centred line carries a full move pair ("6  0-0  Be7"), a White move alone, or
# a Black move introduced by the ellipsis ("4  ...  Bb6"). The leading indent is
# what marks it as the game rather than a variation quoted in the notes.
_CENTRED = re.compile(
    r"^\s{4,}(\d{1,3})\s+(" + _ELLIPSIS + r"|\S+)(?:\s+(\S+))?(?:\s+\(D\))?\s*$"
)

# The part of a move that survives the encoding: disambiguator, capture,
# destination, promotion. Whatever precedes it is the corrupt piece glyph.
_TAIL = re.compile(r"([a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?)[+#]?[!?]{0,2}$")
_PAWN = re.compile(r"^([a-h](?:x[a-h])?[1-8](?:=[QRBN])?)[+#]?[!?]{0,2}$")
_CASTLE = re.compile(r"^[0O]-?[0O](-?[0O])?")

_SAN_ERRORS = (
    ValueError,
    chess.InvalidMoveError,
    chess.IllegalMoveError,
    chess.AmbiguousMoveError,
)


@dataclass(frozen=True)
class BookMove:
    """One move of a reconstructed game, with the author's annotation marks."""

    number: int
    is_white: bool
    san: str
    marks: str  # '!', '?', '!!', '??' … as printed; '' when unannotated
    fen_before: str  # the position the move was played in


@dataclass(frozen=True)
class BookGame:
    """A reconstructed game: every move legal, truncated at the first misread."""

    index: int
    moves: list[BookMove]
    truncated: bool

    @property
    def plies(self) -> int:
        return len(self.moves)


def _norm(token: str) -> str:
    """Undo the OCR's letter/digit confusions inside the square part of a token.

    Only a character sitting immediately after a file letter is rewritten, since a
    rank digit is the only thing that can legally appear there — which leaves the
    piece glyph (full of those same letters) untouched.
    """
    fixes = {"S": "5", "s": "5", "l": "1", "I": "1", "i": "1", "Z": "2", "z": "2"}
    out = list(token)
    for i in range(len(out) - 1):
        if out[i] in "abcdefgh" and out[i + 1] in fixes:
            out[i + 1] = fixes[out[i + 1]]
    return "".join(out)


def classify(glyph: str) -> str | None:
    """Guess the piece from the corrupt figurine glyph, or ``None`` if unreadable.

    The encoding mangles each figurine into a small family of look-alikes, and the
    families barely overlap: the king keeps a '>', the queen a leading apostrophe,
    the rook an 'l:' stem, the bishop a dot, and the knight the upright letters.
    U+FFFD is several figurines collapsed onto one character and so is unreadable
    by construction — the caller then falls back to legality alone.
    """
    if "�" in glyph:
        return None
    if ">" in glyph:
        return "K"
    if glyph.startswith(("'", "1i")):
        return "Q"
    if glyph.startswith("l:"):  # checked before the bishop's dot: 'l:.' is a rook
        return "R"
    if "." in glyph:
        return "B"
    if re.search(r"[DJL]", glyph) or glyph.startswith(("t", "lt", "li")):
        return "N"
    if glyph in ("l", "ll"):
        return "R"
    return None


def looks_like_move(token: str | None) -> bool:
    """Cheap gate: a move names a square or castles.

    Keeps stray prose characters and the book's '(D)' diagram marker out of the
    move stream, where one bogus token would otherwise truncate the whole game.
    """
    if not token:
        return False
    cleaned = _norm(token.strip().rstrip(".,;:)"))
    if cleaned.startswith("("):
        return False
    return bool(_CASTLE.match(cleaned) or re.search(r"[a-h][1-8]", cleaned))


def marks_of(token: str) -> str:
    """The author's annotation marks on a printed move ('!', '??', … or '')."""
    found = re.search(r"([!?]{1,2})$", token.rstrip(".,;:)"))
    return found.group(1) if found else ""


def _candidates(token: str) -> list[str]:
    """SAN spellings this token could be, narrowed by the glyph when legible."""
    cleaned = _norm(token.strip().rstrip(".,;:)"))
    if _CASTLE.match(cleaned):
        castle_long = cleaned.count("0") + cleaned.count("O") > 2
        return ["O-O-O"] if castle_long else ["O-O"]
    pawn = _PAWN.match(cleaned)
    if pawn:
        return [pawn.group(1)]
    tail = _TAIL.search(cleaned)
    if not tail:
        return []
    piece = classify(cleaned[: tail.start(1)])
    return [f"{p}{tail.group(1)}" for p in ((piece,) if piece else PIECES)]


def resolve(board: chess.Board, token: str) -> chess.Move | None:
    """The unique legal move this token names, or ``None`` if none or several fit."""
    found: list[chess.Move] = []
    for candidate in _candidates(token):
        try:
            move = board.parse_san(candidate)
        except _SAN_ERRORS:
            continue
        if move not in found:
            found.append(move)
    return found[0] if len(found) == 1 else None


def _columns(page_text: str, split: int = SPLIT_COL) -> str:
    """Re-serialise a two-column page into true reading order.

    Each physical line holds a slice of both columns, and a book is read down the
    left column and then down the right — so cutting every line at ``split`` and
    emitting all the left halves before all the right halves restores the order
    the moves were actually played in.
    """
    lines = page_text.splitlines()
    left = "\n".join(line[:split].rstrip() for line in lines)
    right = "\n".join(line[split:].rstrip() for line in lines)
    return f"{left}\n{right}"


def read_book(path: Path, first: int = 0, last: int | None = None) -> str:
    """Read a page range in column order, preserving the layout that carries meaning."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    stop = len(reader.pages) if last is None else min(last, len(reader.pages))
    return "\n".join(
        _columns(reader.pages[i].extract_text(extraction_mode="layout") or "")
        for i in range(first, stop)
    )


def parse_moves(text: str) -> list[tuple[int, bool, str]]:
    """Pull ``(move number, is_white, token)`` triples from the centred move lines."""
    out: list[tuple[int, bool, str]] = []
    for line in text.splitlines():
        found = _CENTRED.match(line.rstrip())
        if not found:
            continue
        number, first, second = int(found.group(1)), found.group(2), found.group(3)
        if re.fullmatch(_ELLIPSIS, first):  # "4 ... Bb6" — Black alone
            if looks_like_move(second):
                out.append((number, False, second))
            continue
        if not looks_like_move(first):
            continue
        out.append((number, True, first))
        if looks_like_move(second):  # the pair shared a line
            out.append((number, False, second))
    return out


def split_games(
    triples: list[tuple[int, bool, str]],
) -> list[list[tuple[int, bool, str]]]:
    """Cut the token stream into games: a White move numbered 1 starts a new one."""
    games: list[list[tuple[int, bool, str]]] = []
    current: list[tuple[int, bool, str]] = []
    for triple in triples:
        number, is_white, _ = triple
        if number == 1 and is_white and current:
            games.append(current)
            current = []
        current.append(triple)
    if current:
        games.append(current)
    return games


def replay(triples: list[tuple[int, bool, str]], index: int = 0) -> BookGame:
    """Replay one game, stopping at the first token that will not resolve.

    Stopping rather than skipping is the safe choice: a dropped move makes every
    later position wrong, and a wrong FEN is far worse for a dataset than a short
    game.
    """
    board = chess.Board()
    moves: list[BookMove] = []
    for number, is_white, token in triples:
        # A token whose side does not match the board is prose noise or a running
        # page header; skip it without disturbing the game.
        if is_white != (board.turn == chess.WHITE):
            continue
        if number and number != board.fullmove_number:
            continue
        move = resolve(board, token)
        if move is None:
            return BookGame(index=index, moves=moves, truncated=True)
        moves.append(
            BookMove(
                number=number,
                is_white=is_white,
                san=board.san(move),
                marks=marks_of(token),
                fen_before=board.fen(),
            )
        )
        board.push(move)
    return BookGame(index=index, moves=moves, truncated=False)


def games_from_book(path: Path, first: int = 0, last: int | None = None) -> list[BookGame]:
    """The full pipeline: a book PDF in, verified reconstructed games out."""
    triples = parse_moves(read_book(path, first, last))
    return [replay(game, index=i) for i, game in enumerate(split_games(triples))]

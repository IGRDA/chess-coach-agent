"""Deterministic legality check for a coach's output — structured moves and prose.

An LLM coach can name a move that does not exist in the position. That is a hard,
objective failure no judge is needed to catch: the rules of chess decide it. This
module extracts every move a reply commits to — the structured ``best_move`` and
``line`` fields, plus moves written in the free-text explanation — and checks each is
legal, so the eval can gate on "did the coach only ever name real moves".

It is deliberately lenient about prose to avoid false alarms: a move counts as legal
if it is legal in the given position *or* in any position reached by the moves named
before it (a coach describing a short line). Bare pawn destinations like ``e4`` are
skipped because they are ambiguous with square references ("the e4 pawn"); piece
moves, captures, castling, promotions and UCI are checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import chess

# Disambiguated SAN (piece moves, captures, castling, promotions) and UCI. Bare pawn
# pushes (e4, d5) are intentionally excluded — too easily a square reference in prose;
# pawn *promotions* (e8=Q) and pawn captures (exd5) are kept, being unambiguous moves.
_SAN = (
    r"(?:O-O-O|O-O"
    r"|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]"
    r"|[a-h]x[a-h][1-8](?:=[QRBN])?"
    r"|[a-h][18]=[QRBN])[+#]?"
)
_UCI = r"[a-h][1-8][a-h][1-8][qrbn]?"
_MOVE_RE = re.compile(rf"\b(?:{_SAN}|{_UCI})")


@dataclass(frozen=True)
class LegalityResult:
    """Which named moves were illegal, and a pass flag (no illegal move named)."""

    legal: bool
    illegal: tuple[str, ...] = ()
    checked: int = 0
    sources: dict[str, list[str]] = field(default_factory=dict)

    @property
    def score(self) -> float:
        return 1.0 if self.legal else 0.0


def _try_move(board: chess.Board, token: str) -> chess.Move | None:
    """Parse ``token`` as SAN or UCI; return it only if legal in ``board``."""
    for parse in (board.parse_san, board.parse_uci):
        try:
            move = parse(token)
        except (ValueError, chess.InvalidMoveError, chess.IllegalMoveError):
            continue
        if move in board.legal_moves:
            return move
    return None


_PIECE_LETTER = {
    "K": chess.KING,
    "Q": chess.QUEEN,
    "R": chess.ROOK,
    "B": chess.BISHOP,
    "N": chess.KNIGHT,
}
_DEST_RE = re.compile(r"([KQRBN])[a-h1-8]{0,2}x?([a-h][1-8])")


def _is_location_reference(boards: list[chess.Board], token: str) -> bool:
    """Whether ``token`` names a square a piece of its type already sits on.

    Prose writes a piece's *location* the same way as a move to it — "the king on
    Kh8", "Rf8 is passive". When that piece already stands on the destination in some
    reached position, the token describes where it is, not an (illegal) move to it.
    """
    match = _DEST_RE.fullmatch(token.rstrip("+#"))
    if not match:
        return False
    piece_type = _PIECE_LETTER[match.group(1)]
    square = chess.parse_square(match.group(2))
    return any(
        (p := board.piece_at(square)) is not None and p.piece_type == piece_type
        for board in boards
    )


def _applies_either_turn(board: chess.Board, token: str) -> chess.Board | None:
    """If ``token`` is legal for the side to move — or the other side — return the
    board after it. Prose often lists one side's plan without the opponent's replies,
    so a move should not be called illegal merely for being 'out of turn'."""
    for probe in (board, _with_turn_flipped(board)):
        move = _try_move(probe, token)
        if move is not None:
            after = probe.copy(stack=False)
            after.push(move)
            return after
    return None


def _with_turn_flipped(board: chess.Board) -> chess.Board:
    flipped = board.copy(stack=False)
    flipped.turn = not flipped.turn
    flipped.clear_stack()
    return flipped


def extract_move_tokens(text: str) -> list[str]:
    """Pull candidate move tokens (SAN/UCI) from free text, in order of appearance."""
    return [m.group(0) for m in _MOVE_RE.finditer(text or "")]


def illegal_in_line(fen: str, moves: list[str]) -> list[str]:
    """Return the moves that break a *sequence* from ``fen`` (empty if all legal)."""
    board = chess.Board(fen)
    bad: list[str] = []
    for move in moves:
        parsed = _try_move(board, move)
        if parsed is None:
            bad.append(move)
            break  # the line is broken; later moves are undefined
        board.push(parsed)
    return bad


def _line_anchors(fen: str, line: list[str] | None) -> list[chess.Board]:
    """The positions along a known line — the root and after each legal move — used as
    extra anchors for prose legality, so a coach discussing a move deep in the engine's
    own line is not flagged just because the prose walk could not reach that far."""
    anchors = [chess.Board(fen)]
    if not line:
        return anchors
    board = chess.Board(fen)
    for move in line:
        parsed = _try_move(board, move)
        if parsed is None:
            break
        board.push(parsed)
        anchors.append(board.copy(stack=False))
    return anchors


def illegal_in_prose(
    fen: str, text: str, *, anchors: list[chess.Board] | None = None
) -> list[str]:
    """Moves named in prose that are legal in no reachable position (likely invented).

    Lenient: a token is accepted if it is legal (for either side) at any *anchor*
    position — the root, positions along a known line, or a position reached by an
    earlier accepted token — so a coach narrating a line is not penalised. Only tokens
    illegal everywhere reachable are flagged.
    """
    tokens = extract_move_tokens(text)
    if not tokens:
        return []
    reached = list(anchors) if anchors else [chess.Board(fen)]
    bad: list[str] = []
    for token in tokens:
        extended = None
        for board in reached:
            extended = _applies_either_turn(board, token)
            if extended is not None:
                break
        if extended is not None:
            reached.append(extended)
        elif not _is_location_reference(reached, token):
            bad.append(token)  # illegal everywhere, and not a "piece is here" reference
    return bad


def check_result(
    fen: str | None,
    *,
    best_move: str | None = None,
    line: list[str] | None = None,
    explanation: str | None = None,
) -> LegalityResult:
    """Check every move a coach committed to (structured + prose) against ``fen``.

    Returns ``legal=True`` with nothing to check when there is no board (general
    chat) — legality is undefined without a position.
    """
    if not fen:
        return LegalityResult(legal=True, checked=0)

    sources: dict[str, list[str]] = {}
    checked = 0

    if best_move:
        checked += 1
        if illegal_in_line(fen, [best_move]):
            sources["best_move"] = [best_move]
    if line:
        checked += len(line)
        bad_line = illegal_in_line(fen, line)
        if bad_line:
            sources["line"] = bad_line
    if explanation:
        prose_tokens = extract_move_tokens(explanation)
        checked += len(prose_tokens)
        # Anchor prose legality to the engine line so moves the coach discusses deep in
        # that line are not mistaken for hallucinations.
        anchors = _line_anchors(fen, line)
        bad_prose = illegal_in_prose(fen, explanation, anchors=anchors)
        if bad_prose:
            sources["prose"] = bad_prose

    illegal = tuple(m for moves in sources.values() for m in moves)
    return LegalityResult(
        legal=not illegal, illegal=illegal, checked=checked, sources=sources
    )

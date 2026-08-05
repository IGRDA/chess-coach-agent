"""Deterministic chess tools the coaching skills reason with — beyond the engine.

Three helpers that turn a position into *teaching material* while keeping every
concrete claim grounded in truth:

- :func:`position_features` — an engine-free "quick sight" scan (legal checks,
  captures, and the loose pieces on both sides). This is what a coach glances at
  first, before any calculation.
- :func:`evaluate_move` — score one specific move the student is weighing, as a
  centipawn loss against the engine's best plus a plain-word verdict. Built on the
  :class:`PositionAnalyzer` port, so it reads the *same* ground truth the structured
  answer is graded against.
- :func:`compare_candidates` — rank a supplied shortlist of moves, best first. The
  candidate-comparison step of disciplined calculation, done with the engine as the
  arbiter rather than the coach's guess.

The two engine-backed helpers compose only :meth:`PositionAnalyzer.analyze`, so they
work identically with the app's Stockfish analyzer and the evaluation harness's oracle
analyzer — one source of truth, no separate engine path to drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from chess_coach.adapters.coach.analysis import PositionAnalyzer, format_score

# Move-quality verdicts by centipawns given up versus the engine's best move. These
# are a *different* decision from the assessment buckets: they grade a move relative
# to the best available, not the position in absolute terms.
_INACCURACY_CP = 50
_MISTAKE_CP = 100
_BLUNDER_CP = 300

# Once a move gives up this much it is simply lost; report the loss capped here so a
# crossed mate boundary shows a sane number rather than a mate-scale integer.
_LOSS_CAP = 2000

# A large sentinel so mate scores compare sensibly against centipawns: a faster mate
# beats a slower one, and being mated sooner is worse than being mated later.
_MATE_VALUE = 100_000

_PIECE_VALUE = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}


@dataclass(frozen=True)
class PositionFeatures:
    """A quick-sight reading of a position — the forcing moves and the loose pieces.

    Everything here is exact and engine-free: legal move properties from the rules of
    chess. ``hanging_targets`` are enemy pieces we can win on the spot;
    ``hanging_own`` are our pieces the opponent is threatening. Descriptors read like
    ``Nf6`` (piece letter + square).
    """

    side_to_move: str
    in_check: bool
    checks: list[str] = field(default_factory=list)
    captures: list[str] = field(default_factory=list)
    hanging_targets: list[str] = field(default_factory=list)
    hanging_own: list[str] = field(default_factory=list)
    material: dict[str, int] = field(default_factory=dict)
    castling: str = "-"


@dataclass(frozen=True)
class MoveEval:
    """The engine's verdict on one specific move, relative to the best available."""

    move_uci: str
    move_san: str
    cp_loss: int
    verdict: str  # best | good | inaccuracy | mistake | blunder
    is_best: bool
    score_text: str  # resulting evaluation from the mover's point of view


def _board(fen: str) -> chess.Board:
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError(f"illegal position: {fen!r}")
    return board


def _parse_move(board: chess.Board, move: str) -> chess.Move:
    """Accept a move as UCI or SAN; raise ``ValueError`` if it is not legal here."""
    text = move.strip()
    for parse in (board.parse_uci, board.parse_san):
        try:
            parsed = parse(text)
        except (ValueError, chess.InvalidMoveError):
            continue
        if parsed in board.legal_moves:
            return parsed
    raise ValueError(f"illegal move {move!r} in position {board.fen()!r}")


def _en_prise(board: chess.Board, color: chess.Color) -> list[str]:
    """Pieces of ``color`` that are loose: attacked and either undefended or attacked
    by something cheaper than they are."""
    loose: list[str] = []
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is None or piece.color != color or piece.piece_type == chess.KING:
            continue
        attackers = board.attackers(not color, square)
        if not attackers:
            continue
        defenders = board.attackers(color, square)
        cheapest = min(_PIECE_VALUE[board.piece_at(a).piece_type] for a in attackers)  # type: ignore[union-attr]
        if not defenders or cheapest < _PIECE_VALUE[piece.piece_type]:
            loose.append(f"{piece.symbol().upper()}{chess.square_name(square)}")
    return loose


def _material(board: chess.Board) -> dict[str, int]:
    counts = {"white": 0, "black": 0}
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is None or piece.piece_type == chess.KING:
            continue
        side = "white" if piece.color == chess.WHITE else "black"
        counts[side] += _PIECE_VALUE[piece.piece_type]
    return counts


def position_features(fen: str) -> PositionFeatures:
    """Scan a position for its forcing moves and loose pieces — the quick-sight step."""
    board = _board(fen)
    checks: list[str] = []
    captures: list[str] = []
    for move in board.legal_moves:
        if board.gives_check(move):
            checks.append(board.san(move))
        if board.is_capture(move):
            captures.append(board.san(move))
    us = board.turn
    return PositionFeatures(
        side_to_move="white" if us == chess.WHITE else "black",
        in_check=board.is_check(),
        checks=checks,
        captures=captures,
        hanging_targets=_en_prise(board, not us),
        hanging_own=_en_prise(board, us),
        material=_material(board),
        castling=board.castling_xfen() if board.castling_rights else "-",
    )


@dataclass(frozen=True)
class LegalMove:
    """One legal move, with the properties a coach reasons about at a glance."""

    san: str
    uci: str
    is_check: bool
    is_capture: bool


def legal_moves(fen: str, *, only_checks: bool = False) -> list[LegalMove]:
    """Enumerate the legal moves in a position (optionally only the checking ones).

    The exhaustive, exact set of what is *allowed* here — the ground truth a coach
    uses to build a candidate list, confirm a forcing resource exists, or verify a
    move it is about to name is actually legal. Engine-free: these are the rules of
    chess, not an evaluation. ``only_checks`` narrows it to the moves that give check.
    """
    board = _board(fen)
    moves: list[LegalMove] = []
    for move in board.legal_moves:
        gives_check = board.gives_check(move)
        if only_checks and not gives_check:
            continue
        moves.append(
            LegalMove(
                san=board.san(move),
                uci=move.uci(),
                is_check=gives_check,
                is_capture=board.is_capture(move),
            )
        )
    return moves


def _value_cp(cp: int | None, mate: int | None) -> int:
    """Collapse a (cp, mate) score into a single comparable integer (mover's POV)."""
    if mate is not None:
        return _MATE_VALUE - mate if mate >= 0 else -_MATE_VALUE - mate
    assert cp is not None
    return cp


def _verdict(cp_loss: int, is_best: bool) -> str:
    if is_best:
        return "best"
    if cp_loss < _INACCURACY_CP:
        return "good"
    if cp_loss < _MISTAKE_CP:
        return "inaccuracy"
    if cp_loss < _BLUNDER_CP:
        return "mistake"
    return "blunder"


def evaluate_move(analyzer: PositionAnalyzer, fen: str, move: str) -> MoveEval:
    """Score one move: how much it gives up versus the engine's best, with a verdict.

    The move's value is read from the position it reaches (the engine's evaluation
    there, flipped to the mover's point of view), with the terminal cases —
    checkmate delivered, stalemate — handled without asking the engine to score a
    finished game.
    """
    board = _board(fen)
    parsed = _parse_move(board, move)
    move_uci = parsed.uci()
    move_san = board.san(parsed)

    best = analyzer.analyze(fen)
    best_value = _value_cp(best.cp, best.mate)
    is_best = move_uci == best.best_move_uci
    if is_best:
        return MoveEval(
            move_uci=move_uci,
            move_san=move_san,
            cp_loss=0,
            verdict="best",
            is_best=True,
            score_text=best.score_text(),
        )

    board.push(parsed)
    if board.is_checkmate():
        move_cp, move_mate = None, 0  # mate delivered now
    elif board.is_game_over():  # stalemate, insufficient material, etc. → draw
        move_cp, move_mate = 0, None
    else:
        # Flip the resulting position (scored from the opponent's point of view)
        # back to the mover's: a mate for them is a mate against us, and vice versa.
        after = analyzer.analyze(board.fen())
        if after.mate is not None:
            move_cp, move_mate = None, -after.mate
        else:
            assert after.cp is not None
            move_cp, move_mate = -after.cp, None

    move_value = _value_cp(move_cp, move_mate)
    cp_loss = min(max(0, best_value - move_value), _LOSS_CAP)
    return MoveEval(
        move_uci=move_uci,
        move_san=move_san,
        cp_loss=cp_loss,
        verdict=_verdict(cp_loss, is_best),
        is_best=is_best,
        score_text=format_score(move_cp, move_mate),
    )


def compare_candidates(
    analyzer: PositionAnalyzer, fen: str, moves: list[str]
) -> list[MoveEval]:
    """Evaluate a shortlist of candidate moves and rank them, best first."""
    if not moves:
        raise ValueError("compare_candidates needs at least one candidate move")
    evals = [evaluate_move(analyzer, fen, move) for move in moves]
    return sorted(evals, key=lambda e: e.cp_loss)

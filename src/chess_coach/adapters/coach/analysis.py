"""The coach's objective reading of a position: what Stockfish sees.

Defines the small value object (:class:`PositionAnalysis`) and the port
(:class:`PositionAnalyzer`) through which the coaching agent gets *ground truth*
about a position — the best move, a centipawn/mate score, a coarse human bucket,
and the win/draw/loss verdict. The agent never guesses these; it reads them here,
which is the whole point of pairing an LLM coach with an engine.

Why a port, not a concrete engine here: the thresholds that turn a raw score into
a bucket or a result are a *decision*, and different callers may already own that
decision. The evaluation harness, in particular, authored its dataset with its own
pinned Stockfish and bucket scale; letting it supply the analyzer keeps the coach's
answers defined by exactly one source of truth instead of a near-duplicate that can
drift. A default Stockfish-backed analyzer (:class:`StockfishAnalyzer`) is provided
for the app itself.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import threading
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import chess
import chess.engine

Bucket = Literal["losing", "worse", "equal", "better", "winning"]
Result = Literal["win", "draw", "loss"]


@dataclass(frozen=True)
class PositionAnalysis:
    """Engine ground truth for a position, from the side-to-move point of view."""

    best_move_uci: str
    best_move_san: str
    cp: int | None
    mate: int | None
    bucket: Bucket
    result: Result
    # The engine's principal variation: its best line for *both* sides, in order
    # (our move, the expected reply, our follow-up, …). This is the deep-sequence
    # truth for calculating a continuation; ``()`` when the engine returned none.
    pv_uci: tuple[str, ...] = ()
    pv_san: tuple[str, ...] = ()

    def score_text(self) -> str:
        """A short human reading of the score, e.g. ``#3`` or ``+1.35``."""
        return format_score(self.cp, self.mate)


@dataclass(frozen=True)
class TopMove:
    """One of the engine's best moves (from MultiPV), with its score."""

    uci: str
    san: str
    score: str  # side-to-move POV, e.g. "#2" or "+0.80"


def format_score(cp: int | None, mate: int | None) -> str:
    """Render a (cp, mate) score as a short human string, e.g. ``#3`` or ``+1.35``.

    ``mate == 0`` means checkmate is on the board *now* (rendered ``#``); a positive
    mate is *for* the side to move, a negative one *against* it.
    """
    if mate is not None:
        if mate == 0:
            return "#"
        return f"#{mate}" if mate > 0 else f"#-{abs(mate)}"
    assert cp is not None
    return f"{cp / 100:+.2f}"


@runtime_checkable
class PositionAnalyzer(Protocol):
    """Turns a FEN into :class:`PositionAnalysis` — the coach's engine oracle."""

    def analyze(self, fen: str) -> PositionAnalysis: ...


# Bucket thresholds and the decisive-score cutoff (side-to-move centipawns). These
# mirror the evaluation harness's scale so the default analyzer and the graded
# dataset speak the same language; the harness can still inject its own.
_BETTER_CP = 100
_WINNING_CP = 300
_DECISIVE_CP = 300

# Pinned search: fixed depth/threads/hash so the same position yields the same
# reading run to run — a coach that contradicts itself teaches nothing.
DEFAULT_DEPTH = 18
DEFAULT_THREADS = 1
DEFAULT_HASH_MB = 64


def bucket_from_score(cp: int | None, mate: int | None) -> Bucket:
    """Map a score (side-to-move POV) to a coarse human bucket."""
    if mate is not None:
        return "winning" if mate > 0 else "losing"
    if cp is None:
        raise ValueError("either cp or mate must be provided")
    if cp >= _WINNING_CP:
        return "winning"
    if cp >= _BETTER_CP:
        return "better"
    if cp <= -_WINNING_CP:
        return "losing"
    if cp <= -_BETTER_CP:
        return "worse"
    return "equal"


def result_from_score(cp: int | None, mate: int | None) -> Result:
    """Reduce a score to a win/draw/loss verdict for the side to move."""
    if mate is not None:
        return "win" if mate > 0 else "loss"
    assert cp is not None
    if cp >= _DECISIVE_CP:
        return "win"
    if cp <= -_DECISIVE_CP:
        return "loss"
    return "draw"


def _render_pv(
    board: chess.Board, pv: list[chess.Move]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Render a principal variation to parallel (UCI, SAN) tuples.

    Walks a *copy* of the board so the caller's position is untouched; SAN needs the
    running board because a move's short name depends on the pieces around it.
    """
    walker = board.copy(stack=False)
    uci: list[str] = []
    san: list[str] = []
    for move in pv:
        san.append(walker.san(move))
        uci.append(move.uci())
        walker.push(move)
    return tuple(uci), tuple(san)


class MemoizingAnalyzer:
    """Wrap a :class:`PositionAnalyzer` with a thread-safe, single-flight per-FEN memo.

    Two wins, both from the fact that an analysis is deterministic given the FEN:

    * **Prefetch.** :meth:`prefetch` warms the cache from a worker thread the moment a
      position is known, so by the time the model asks for ``analyze_position`` the
      engine has usually already thought — trading spare computation for latency.
    * **Deduplication.** A turn often analyses the same FEN more than once (the best
      move, then a move the student is weighing); the memo collapses those to one
      engine search. A per-FEN lock makes a concurrent prefetch and tool call share a
      single computation instead of racing the one engine process.
    """

    def __init__(self, inner: PositionAnalyzer) -> None:
        self._inner = inner
        self._cache: dict[str, PositionAnalysis] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, fen: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(fen, threading.Lock())

    def analyze(self, fen: str) -> PositionAnalysis:
        cached = self._cache.get(fen)
        if cached is not None:
            return cached
        with self._lock_for(fen):
            cached = self._cache.get(fen)
            if cached is not None:  # filled while we waited for the lock
                return cached
            analysis = self._inner.analyze(fen)
            self._cache[fen] = analysis
            return analysis

    def prefetch(self, fen: str) -> None:
        """Compute and cache the analysis, swallowing errors (best-effort warm-up)."""
        with contextlib.suppress(ValueError, RuntimeError):
            self.analyze(fen)


class EngineUnavailableError(RuntimeError):
    """Raised when no Stockfish binary can be located."""


def find_stockfish() -> str:
    """Locate the Stockfish binary, or raise :class:`EngineUnavailableError`."""
    binary = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")
    if not binary:
        raise EngineUnavailableError(
            "Stockfish not found; set STOCKFISH_PATH or `brew install stockfish`."
        )
    return binary


class StockfishAnalyzer:
    """Default :class:`PositionAnalyzer`: a pinned Stockfish process.

    Use as a context manager so the engine is always torn down::

        with StockfishAnalyzer() as sf:
            sf.analyze(fen)
    """

    def __init__(
        self, binary: str | None = None, *, depth: int = DEFAULT_DEPTH
    ) -> None:
        self._binary = binary or find_stockfish()
        self._depth = depth
        self._engine: chess.engine.SimpleEngine | None = None

    def __enter__(self) -> StockfishAnalyzer:
        self._engine = chess.engine.SimpleEngine.popen_uci(self._binary)
        self._engine.configure({"Threads": DEFAULT_THREADS, "Hash": DEFAULT_HASH_MB})
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    def analyze(self, fen: str) -> PositionAnalysis:
        if self._engine is None:
            raise RuntimeError("StockfishAnalyzer used outside a `with` block")
        board = chess.Board(fen)
        if not board.is_valid():
            raise ValueError(f"illegal position: {fen!r}")
        # A fresh game token forces `ucinewgame`, clearing the transposition table
        # so a prior position can't sway which of several equal-best moves returns.
        info = self._engine.analyse(
            board, chess.engine.Limit(depth=self._depth), game=object()
        )
        pov = info["score"].relative
        mate = pov.mate()
        cp = None if mate is not None else pov.score()
        pv = info.get("pv") or []
        if not pv:
            raise RuntimeError(f"engine returned no principal variation for {fen!r}")
        best = pv[0]
        pv_uci, pv_san = _render_pv(board, pv)
        return PositionAnalysis(
            best_move_uci=best.uci(),
            best_move_san=board.san(best),
            cp=cp,
            mate=mate,
            bucket=bucket_from_score(cp, mate),
            result=result_from_score(cp, mate),
            pv_uci=pv_uci,
            pv_san=pv_san,
        )

    def top_moves(self, fen: str, n: int = 3) -> list[TopMove]:
        """The engine's ``n`` best moves (MultiPV), each with its score.

        The *set* of engine-verified-strong moves, best first. A coach can pick the
        most instructive of these knowing every one is objectively sound — the point
        of MultiPV over a single best move, which forces one arbitrary choice among
        equals.
        """
        if self._engine is None:
            raise RuntimeError("StockfishAnalyzer used outside a `with` block")
        board = chess.Board(fen)
        if not board.is_valid():
            raise ValueError(f"illegal position: {fen!r}")
        infos = self._engine.analyse(
            board, chess.engine.Limit(depth=self._depth), multipv=n, game=object()
        )
        moves: list[TopMove] = []
        for info in infos:
            pv = info.get("pv") or []
            if not pv:
                continue
            pov = info["score"].relative
            mate = pov.mate()
            cp = None if mate is not None else pov.score()
            moves.append(
                TopMove(
                    uci=pv[0].uci(),
                    san=board.san(pv[0]),
                    score=format_score(cp, mate),
                )
            )
        return moves

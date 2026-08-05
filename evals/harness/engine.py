"""The pinned Stockfish oracle: objective ground truth for grading.

Wraps a Stockfish UCI process (via python-chess) behind a tiny interface and
*pins* the search — fixed depth, single thread, fixed hash — so the same position
yields the same assessment run to run. That determinism is what lets a golden's
stored ``expected_bucket`` be trusted and lets the reference ``OracleTask`` agree
with the dataset. Everything UCI-specific stays inside this module.

Requires a Stockfish binary: found via ``$STOCKFISH_PATH`` or ``stockfish`` on the
``PATH`` (``brew install stockfish``). Use it as a context manager so the engine
process is always torn down.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from types import TracebackType

import chess
import chess.engine

from evals.harness.checkers import Bucket, bucket_from_score, to_board

DEFAULT_DEPTH = 18
DEFAULT_THREADS = 1
DEFAULT_HASH_MB = 64

# Beyond this centipawn/mate reading the side to move is treated as objectively
# winning (or, negated, losing) when reducing an endgame to win/draw/loss.
_DECISIVE_CP = 300


class EngineUnavailableError(RuntimeError):
    """Raised when no Stockfish binary can be located."""


def find_stockfish() -> str:
    """Locate the Stockfish binary, or raise ``EngineUnavailableError``."""
    binary = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")
    if not binary:
        raise EngineUnavailableError(
            "Stockfish not found; set STOCKFISH_PATH or `brew install stockfish`."
        )
    return binary


@dataclass(frozen=True)
class Assessment:
    """The oracle's pinned reading of a position, from the side-to-move POV."""

    best_move_uci: str
    cp: int | None
    mate: int | None
    bucket: Bucket
    # The engine's principal variation as UCI (its best line for both sides). Empty
    # tuple keeps older call sites that build an Assessment directly still valid.
    pv_uci: tuple[str, ...] = ()

    def result(self) -> str:
        """Reduce the assessment to a win/draw/loss verdict for the mover."""
        if self.mate is not None:
            return "win" if self.mate > 0 else "loss"
        assert self.cp is not None
        if self.cp >= _DECISIVE_CP:
            return "win"
        if self.cp <= -_DECISIVE_CP:
            return "loss"
        return "draw"


class StockfishOracle:
    """A pinned Stockfish process exposing deterministic assessments.

    Open with a ``with`` block; :meth:`assess` returns the best move, score and
    bucket for a FEN under the fixed search limits.
    """

    def __init__(
        self,
        binary: str | None = None,
        *,
        depth: int = DEFAULT_DEPTH,
        threads: int = DEFAULT_THREADS,
        hash_mb: int = DEFAULT_HASH_MB,
    ) -> None:
        self._binary = binary or find_stockfish()
        self._depth = depth
        self._threads = threads
        self._hash_mb = hash_mb
        self._engine: chess.engine.SimpleEngine | None = None

    def __enter__(self) -> StockfishOracle:
        self._engine = chess.engine.SimpleEngine.popen_uci(self._binary)
        self._engine.configure({"Threads": self._threads, "Hash": self._hash_mb})
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    def assess(self, fen: str) -> Assessment:
        """Return the pinned best move, score and bucket for ``fen``."""
        if self._engine is None:
            raise RuntimeError("StockfishOracle used outside a `with` block")
        board = to_board(fen)
        # A fresh `game` token makes python-chess send `ucinewgame`, clearing the
        # transposition table so each position is searched from a clean slate.
        # Without this, TT carryover lets an earlier position change which of
        # several equally-best moves is returned — breaking reproducibility.
        info = self._engine.analyse(
            board, chess.engine.Limit(depth=self._depth), game=object()
        )
        pov = info["score"].relative
        mate = pov.mate()
        cp = None if mate is not None else pov.score()
        pv = info.get("pv") or []
        if not pv:
            raise RuntimeError(f"engine returned no principal variation for {fen!r}")
        return Assessment(
            best_move_uci=pv[0].uci(),
            cp=cp,
            mate=mate,
            bucket=bucket_from_score(cp, mate),
            pv_uci=tuple(m.uci() for m in pv),
        )

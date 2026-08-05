"""Warm the engine for the position on the board, before the student asks about it.

Stockfish is the one slow thing the coach's tools do, and it is perfectly
predictable: whatever the coach is asked next, it will be asked about the position
currently on the board. So there is no reason to start thinking when the question
arrives. :class:`PositionPrefetcher` starts the search the moment the board reaches a
legal position, on a background thread, so the ``analyze_position`` call that follows
reads a cached answer instead of waiting on a search.

Only the *timing* changes. The prefetcher fills the same :class:`MemoizingAnalyzer`
the tools already read, with the same pinned-depth search, so the coach sees byte-for-
byte the same ground truth it would have computed on demand.

Newest position wins: if the student keeps moving pieces, a superseded position is
dropped rather than queued, so scrubbing through a game cannot build a backlog of
searches for boards nobody is looking at any more.
"""

from __future__ import annotations

import threading

import chess

from chess_coach.adapters.coach.analysis import MemoizingAnalyzer


class PositionPrefetcher:
    """Keeps the live board's engine analysis warm on a background thread."""

    def __init__(self, analyzer: MemoizingAnalyzer) -> None:
        self._analyzer = analyzer
        self._pending: str | None = None
        self._wake = threading.Condition()
        self._worker: threading.Thread | None = None
        self._closed = False

    def schedule(self, fen: str) -> None:
        """Warm ``fen`` in the background, superseding any position still pending.

        Cheap and safe to call on every board change: an illegal or finished position
        is ignored, and a position already analysed is a no-op.
        """
        if self._closed or not _is_analyzable(fen):
            return
        with self._wake:
            self._pending = fen
            self._ensure_worker()
            self._wake.notify()

    def close(self) -> None:
        """Stop the worker; further :meth:`schedule` calls are ignored."""
        with self._wake:
            self._closed = True
            self._wake.notify_all()

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._run, name="position-prefetch", daemon=True
            )
            self._worker.start()

    def _run(self) -> None:
        while True:
            with self._wake:
                while self._pending is None and not self._closed:
                    self._wake.wait()
                if self._closed:
                    return
                fen, self._pending = self._pending, None
            assert fen is not None
            # `prefetch` swallows engine errors: a position we cannot warm simply
            # isn't cached, and the tool call will surface the real error later.
            self._analyzer.prefetch(fen)


def _is_analyzable(fen: str) -> bool:
    """Whether a FEN is a legal, non-terminal position worth spending a search on."""
    try:
        board = chess.Board(fen)
    except ValueError:
        return False
    return board.is_valid() and bool(list(board.legal_moves))

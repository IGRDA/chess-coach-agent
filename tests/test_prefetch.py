"""The engine warm-up: right answers, earlier — and never a wrong one.

The prefetcher exists purely to move engine work off the critical path, so what these
tests pin down is that it changes *timing only*: the same analysis, computed once, for
the position actually on the board.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import chess
import pytest

from chess_coach.adapters.coach.analysis import (
    MemoizingAnalyzer,
    PositionAnalysis,
    PositionAnalyzer,
)
from chess_coach.adapters.coach.prefetch import PositionPrefetcher

STARTING_FEN = chess.STARTING_FEN
AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
AFTER_E4_E5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"


class SlowAnalyzer:
    """A stand-in engine: records every FEN it searched and takes its time."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.seen: list[str] = []
        self._lock = threading.Lock()

    def analyze(self, fen: str) -> PositionAnalysis:
        with self._lock:
            self.seen.append(fen)
        time.sleep(self.delay)
        return PositionAnalysis(
            best_move_uci="e2e4",
            best_move_san="e4",
            cp=20,
            mate=None,
            bucket="equal",
            result="draw",
        )


def _settle(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    """Wait for a background worker to reach a state, without pinning a duration."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_prefetch_warms_the_cache_so_the_later_read_is_free() -> None:
    inner = SlowAnalyzer()
    analyzer = MemoizingAnalyzer(inner)
    prefetcher = PositionPrefetcher(analyzer)

    prefetcher.schedule(STARTING_FEN)
    assert _settle(lambda: inner.seen == [STARTING_FEN])

    analyzer.analyze(STARTING_FEN)
    assert inner.seen == [STARTING_FEN]  # the read hit the warm cache
    prefetcher.close()


def test_prefetched_answer_is_the_answer_the_tool_would_have_computed() -> None:
    inner = SlowAnalyzer()
    analyzer = MemoizingAnalyzer(inner)
    prefetcher = PositionPrefetcher(analyzer)

    cold = MemoizingAnalyzer(SlowAnalyzer()).analyze(STARTING_FEN)
    prefetcher.schedule(STARTING_FEN)
    assert _settle(lambda: bool(inner.seen))

    assert analyzer.analyze(STARTING_FEN) == cold
    prefetcher.close()


def test_a_superseded_position_is_dropped_not_queued() -> None:
    """Shuffling pieces must not build a backlog of searches nobody is waiting on."""
    inner = SlowAnalyzer(delay=0.25)
    prefetcher = PositionPrefetcher(MemoizingAnalyzer(inner))

    prefetcher.schedule(STARTING_FEN)
    assert _settle(lambda: inner.seen == [STARTING_FEN])  # worker is busy on this one
    # While that search runs, the student plays two more moves.
    prefetcher.schedule(AFTER_E4)
    prefetcher.schedule(AFTER_E4_E5)
    assert _settle(lambda: len(inner.seen) == 2)
    time.sleep(0.4)  # long enough for a queued third search to have shown up

    # Only the board the student is actually looking at got searched.
    assert inner.seen == [STARTING_FEN, AFTER_E4_E5]
    prefetcher.close()


@pytest.mark.parametrize(
    "fen",
    [
        "not a fen",
        "8/8/8/8/8/8/8/8 w - - 0 1",  # no kings: illegal
        "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",  # checkmate: nothing to search
    ],
)
def test_unplayable_positions_are_ignored(fen: str) -> None:
    inner = SlowAnalyzer()
    prefetcher = PositionPrefetcher(MemoizingAnalyzer(inner))

    prefetcher.schedule(fen)
    time.sleep(0.1)

    assert inner.seen == []
    prefetcher.close()


def test_close_stops_further_warming() -> None:
    inner = SlowAnalyzer()
    prefetcher = PositionPrefetcher(MemoizingAnalyzer(inner))

    prefetcher.close()
    prefetcher.schedule(STARTING_FEN)
    time.sleep(0.1)

    assert inner.seen == []


def test_prefetcher_satisfies_the_analyzer_port() -> None:
    assert isinstance(MemoizingAnalyzer(SlowAnalyzer()), PositionAnalyzer)

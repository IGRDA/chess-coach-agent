"""Shared pytest fixtures for the test suite.

Provides the network-free scaffolding the outer layers need to be tested without
Stockfish, Claude or the network: chiefly a fake :class:`CoachPort` that records
the requests it receives and returns a canned result, plus a couple of sample
FENs. Use-case and interface tests share these so the tracing-bullet path (CLI →
use case → coach port) can be exercised end-to-end, fast and deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from chess_coach.application.dto import CoachingRequest, CoachingResult

# The standard starting position and a simple middlegame FEN, handy across tests.
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
SCHOLARS_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4"


@dataclass
class FakeCoach:
    """A :class:`CoachPort` double: returns ``result`` and records every call."""

    result: CoachingResult = field(
        default_factory=lambda: CoachingResult(
            best_move="f3f7",
            eval_bucket="winning",
            result="win",
            explanation="Qxf7 is checkmate — the classic Scholar's Mate.",
        )
    )
    calls: list[CoachingRequest] = field(default_factory=list)

    def coach(self, request: CoachingRequest) -> CoachingResult:
        self.calls.append(request)
        return self.result


@pytest.fixture
def fake_coach() -> FakeCoach:
    return FakeCoach()

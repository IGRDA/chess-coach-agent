"""Application use-case tests.

Exercises the :class:`CoachPosition` use case against the fake coach port from
conftest.py: it forwards a valid request to the port and returns the result, and
it rejects an unknown task in the domain's own vocabulary before touching the
port. Fast and fully isolated from Stockfish, Claude and the network.
"""

from __future__ import annotations

import pytest

from chess_coach.application.dto import CoachingRequest
from chess_coach.application.use_cases.coach_position import CoachPosition
from chess_coach.domain.errors import UnknownTaskError

from ..conftest import SCHOLARS_FEN, FakeCoach


def test_forwards_valid_request_and_returns_result(fake_coach: FakeCoach) -> None:
    use_case = CoachPosition(fake_coach)
    request = CoachingRequest(fen=SCHOLARS_FEN, task="best_move", level="beginner")

    result = use_case.execute(request)

    assert result is fake_coach.result
    assert fake_coach.calls == [request]


def test_forwards_explain_task_with_free_form_question(fake_coach: FakeCoach) -> None:
    use_case = CoachPosition(fake_coach)
    request = CoachingRequest(
        fen=SCHOLARS_FEN,
        task="explain",
        question="Why is White winning?",
        candidate_move="f3f7",
    )

    result = use_case.execute(request)

    assert result is fake_coach.result
    assert fake_coach.calls == [request]


def test_rejects_unknown_task_before_calling_coach(fake_coach: FakeCoach) -> None:
    use_case = CoachPosition(fake_coach)
    request = CoachingRequest(fen=SCHOLARS_FEN, task="tablebase", level=None)

    with pytest.raises(UnknownTaskError):
        use_case.execute(request)

    assert fake_coach.calls == []

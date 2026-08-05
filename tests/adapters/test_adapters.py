"""Adapter and contract tests.

Verifies the coach adapter honours the :class:`CoachPort` contract without a live
model or engine: it rejects an illegal FEN up front (translating python-chess into
the domain error), and on a legal FEN it maps the underlying agent's structured
:class:`CoachAnswer` into a :class:`CoachingResult`. The agent is replaced by a
stub so no Claude call is made.
"""

from __future__ import annotations

import pytest

from chess_coach.adapters.coach.agent import CoachAnswer
from chess_coach.adapters.coach.coach_port import AgentCoachAdapter
from chess_coach.application.dto import CoachingRequest
from chess_coach.domain.errors import InvalidPositionError

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class StubAgent:
    """Stands in for AgentCoach: records the call and returns a canned answer."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, str | None, str | None]] = []

    def answer_sync(
        self,
        fen: str,
        task_type: str,
        level: str | None = None,
        question: str | None = None,
        candidate_move: str | None = None,
    ) -> CoachAnswer:
        self.calls.append((fen, task_type, level, question, candidate_move))
        return CoachAnswer(
            best_move="e2e4",
            eval_bucket="equal",
            result=None,
            explanation="A principled central advance.",
        )


def test_rejects_illegal_fen_before_running_agent() -> None:
    agent = StubAgent()
    adapter = AgentCoachAdapter(agent)

    with pytest.raises(InvalidPositionError):
        adapter.coach(CoachingRequest(fen="not a fen", task="best_move"))

    assert agent.calls == []


def test_maps_agent_answer_to_result() -> None:
    agent = StubAgent()
    adapter = AgentCoachAdapter(agent)

    result = adapter.coach(
        CoachingRequest(fen=START_FEN, task="best_move", level="beginner")
    )

    assert agent.calls == [(START_FEN, "best_move", "beginner", None, None)]
    assert result.best_move == "e2e4"
    assert result.eval_bucket == "equal"
    assert result.explanation == "A principled central advance."


def test_forwards_question_and_candidate_move() -> None:
    agent = StubAgent()
    adapter = AgentCoachAdapter(agent)

    adapter.coach(
        CoachingRequest(
            fen=START_FEN,
            task="explain",
            question="What are the candidate moves here?",
            candidate_move="e2e4",
        )
    )

    assert agent.calls == [
        (START_FEN, "explain", None, "What are the candidate moves here?", "e2e4")
    ]

"""CoachPort adapter: the agent brain behind the application boundary.

Wraps :class:`~chess_coach.adapters.coach.agent.AgentCoach` (the Claude agent
grounded in Stockfish + opening theory) so it satisfies the application's
:class:`~chess_coach.application.ports.coach.CoachPort`. Two jobs, both boundary
work: validate the FEN up front and translate a bad one into the domain's
:class:`~chess_coach.domain.errors.InvalidPositionError` (rather than paying for a
model run that would only fail), and map the agent's structured
:class:`~chess_coach.adapters.coach.agent.CoachAnswer` onto a
:class:`~chess_coach.application.dto.CoachingResult`.

The agent is injected as a small structural type (:class:`_Agent`) so the mapping
can be tested without a live model.
"""

from __future__ import annotations

from typing import Protocol

import chess

from chess_coach.adapters.coach.agent import CoachAnswer
from chess_coach.application.dto import CoachingRequest, CoachingResult
from chess_coach.domain.errors import InvalidPositionError


class _Agent(Protocol):
    """The slice of AgentCoach this adapter drives."""

    def answer_sync(
        self,
        fen: str,
        task_type: str,
        level: str | None = None,
        question: str | None = None,
        candidate_move: str | None = None,
    ) -> CoachAnswer: ...


class AgentCoachAdapter:
    """Adapts :class:`AgentCoach` to the :class:`CoachPort` contract."""

    def __init__(self, agent: _Agent) -> None:
        self._agent = agent

    def coach(self, request: CoachingRequest) -> CoachingResult:
        _validate_fen(request.fen)
        answer = self._agent.answer_sync(
            request.fen,
            request.task,
            request.level,
            request.question,
            request.candidate_move,
        )
        return CoachingResult(
            best_move=answer.best_move,
            eval_bucket=answer.eval_bucket,
            result=answer.result,
            explanation=answer.explanation,
            line=answer.line,
        )


def _validate_fen(fen: str) -> None:
    """Raise :class:`InvalidPositionError` unless ``fen`` is a legal position."""
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise InvalidPositionError(f"not a legal position: {fen!r}") from exc
    if not board.is_valid():
        raise InvalidPositionError(f"not a legal position: {fen!r}")

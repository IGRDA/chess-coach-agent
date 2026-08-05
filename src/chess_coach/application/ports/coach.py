"""CoachPort: the boundary to the natural-language coaching brain.

The seam behind which the Claude agent lives. It turns a coaching request (a
position, the question asked of it, the audience level) into an engine-grounded
answer, hiding all LLM/agent orchestration behind one narrow method. The
implementation returns application DTOs, never raw model responses, and surfaces
failures as domain errors (:class:`~chess_coach.domain.errors.CoachError`), never
SDK exceptions.

Tracing-bullet slice: a single :meth:`CoachPort.coach` call. As the game-review
and lesson use cases land, they add their own methods here; the audience level
stays an explicit parameter on the request, never hard-coded.

``TASKS`` is the closed set of coaching tasks the port understands — the use case
validates against it so an unknown task is rejected in the domain's vocabulary
before any adapter runs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chess_coach.application.dto import CoachingRequest, CoachingResult

TASKS: frozenset[str] = frozenset(
    {"best_move", "eval_bucket", "endgame", "explain", "deep_line"}
)


@runtime_checkable
class CoachPort(Protocol):
    """Turns a :class:`CoachingRequest` into a grounded :class:`CoachingResult`."""

    def coach(self, request: CoachingRequest) -> CoachingResult: ...

"""CoachPosition use case: coach a single position.

The narrow end of the tracing bullet. Given a coaching request it enforces the one
rule it owns — the task must be one the coach understands — and then hands the
request to the :class:`CoachPort`, returning the grounded answer. It holds no I/O:
the delivery layer builds the request and renders the result, so the orchestration
stays trivially testable against a fake port.

Position legality is not checked here on purpose — turning a FEN into a board is a
python-chess concern that belongs in the adapter (the domain and use cases stay
dependency-free). The adapter raises
:class:`~chess_coach.domain.errors.InvalidPositionError` for a bad FEN.
"""

from __future__ import annotations

from chess_coach.application.dto import CoachingRequest, CoachingResult
from chess_coach.application.ports.coach import TASKS, CoachPort
from chess_coach.domain.errors import UnknownTaskError


class CoachPosition:
    """Coach one position through the :class:`CoachPort`."""

    def __init__(self, coach: CoachPort) -> None:
        self._coach = coach

    def execute(self, request: CoachingRequest) -> CoachingResult:
        if request.task not in TASKS:
            known = ", ".join(sorted(TASKS))
            raise UnknownTaskError(
                f"unknown task {request.task!r}; choose one of {known}"
            )
        return self._coach.coach(request)

"""`coach` command: coach a single position from a FEN.

The tracing-bullet verb. It takes a position and what is being asked of it, drives
the :class:`CoachPosition` use case, and renders the engine-grounded answer through
the presenter. The pure part lives in :func:`run` — no argument parsing, no I/O —
so it is unit-testable against a fake coach; app.py owns the terminal read/print
and error translation.

(The interactive live-play loop the fuller design envisions is a later verb; this
module is the one-shot "coach this position" slice that proves the path.)
"""

from __future__ import annotations

from chess_coach.application.dto import CoachingRequest
from chess_coach.application.ports.coach import CoachPort
from chess_coach.application.use_cases.coach_position import CoachPosition
from chess_coach.interface.cli.presenters import present_coaching


def run(coach: CoachPort, request: CoachingRequest) -> str:
    """Coach one position and return the rendered answer as printable text."""
    result = CoachPosition(coach).execute(request)
    return present_coaching(request, result)

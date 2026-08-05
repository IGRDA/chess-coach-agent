"""Presenters: adapt use-case result DTOs into rendered CLI output.

Sits between the use cases and rendering.py: takes a result DTO, selects the view
data worth showing, and composes it with the rendering primitives. This keeps the
command modules to a single call and concentrates presentation decisions here. No
business decisions, no I/O — it returns text.

Tracing-bullet slice: :func:`present_coaching` renders a position assessment (the
board, the populated answer fields, and the coach's explanation).
"""

from __future__ import annotations

from chess_coach.application.dto import CoachingRequest, CoachingResult
from chess_coach.interface.cli.rendering import board_diagram, field_line

# Which result fields to show, in order, with their display labels.
_FIELDS: tuple[tuple[str, str], ...] = (
    ("best_move", "Best move"),
    ("eval_bucket", "Assessment"),
    ("result", "Result"),
)


def present_coaching(request: CoachingRequest, result: CoachingResult) -> str:
    """Compose the full coaching answer for a position into printable text."""
    lines = [board_diagram(request.fen), ""]
    for attr, label in _FIELDS:
        value = getattr(result, attr)
        if value:
            lines.append(field_line(label, value))
    if result.line:
        lines.append(field_line("Line", " ".join(result.line)))
    if result.explanation:
        lines.extend(["", "Coach:", result.explanation])
    return "\n".join(lines)

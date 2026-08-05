"""The port for live, multi-turn coaching — a conversation, not a one-shot answer.

Where :class:`~chess_coach.application.ports.coach.CoachPort` turns one request into
one structured result, :class:`ChatCoachPort` holds an open conversation: the student
speaks, the coach streams a reply, and the exchange is remembered across turns. The
delivery layer (the TUI) depends on this interface so it can be driven by a fake in
tests, exactly as it does for the one-shot coach.

Three capabilities, deliberately separate:

- :meth:`stream` — the conversation itself. It yields the coach's reply in pieces so a
  front-end can render it as it arrives, and it carries the *current* FEN each turn
  because the board may change mid-conversation.
- :meth:`assess` — a direct, engine-only read of a position (its assessment bucket),
  used to reveal ground truth on demand. Kept apart from the conversation so the coach
  can stay spoiler-controlled while the student can still peek at the evaluation.
- :meth:`prefetch` — a hint, not a request: "the board is here now, you will probably
  be asked about it." It returns immediately and answers nothing. A front-end calls it
  on every board change so the engine has already thought by the time the student
  finishes typing; ignoring it changes only latency, never the answer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class ChatCoachPort(Protocol):
    """An open coaching conversation grounded in the engine."""

    def stream(
        self, fen: str, message: str, level: str | None = None
    ) -> AsyncIterator[str]:
        """Send one student turn and stream back the coach's reply in pieces."""
        ...

    def assess(self, fen: str) -> str:
        """The engine's assessment bucket for a position (losing…winning)."""
        ...

    def prefetch(self, fen: str) -> None:
        """Hint that ``fen`` is the live board; warm the engine for it and return."""
        ...

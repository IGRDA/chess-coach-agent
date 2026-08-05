"""The port for the free-form *open chat* — a conversation with no board attached.

Where :class:`~chess_coach.application.ports.chat.ChatCoachPort` is a coach bolted to
the engine and threaded with the live FEN each turn, this is deliberately barer: the
student asks anything at all — a rules question, an opening name, something with no
chess in it — and the assistant answers from its own knowledge. No position, no engine,
no tools. The TUI depends on this interface so a fake can drive it in tests, exactly as
it does for the grounded coach.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class OpenChatPort(Protocol):
    """An open, board-free assistant conversation."""

    def stream(self, message: str) -> AsyncIterator[str]:
        """Send one user turn and stream back the assistant's reply in pieces."""
        ...

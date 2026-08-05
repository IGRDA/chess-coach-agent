"""A free-form assistant conversation for the TUI's *open chat* mode.

Where :class:`~chess_coach.adapters.coach.chat.ChatSession` is a chess coach bolted to
the engine, this is the opposite: a plain, persistent Claude conversation the student
can use to ask anything at all — a rules question, an opening name, or something with no
chess in it. No FEN is threaded, no engine tools are exposed, and no coaching skill is
loaded; it just remembers the dialogue and streams the reply.

Deep module: open it as an async context manager, then call :meth:`stream` per user
turn. The tool allowlist is empty and the filesystem/web tools are denied, so the
session can only talk — it answers from its own knowledge.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)

from chess_coach.adapters.coach.agent import DEFAULT_MODEL
from chess_coach.adapters.observability import tracing

_OPEN_CHAT_SYSTEM_PROMPT = (
    "You are a friendly, knowledgeable assistant chatting with someone who is also "
    "using a chess-coaching app. Answer whatever they ask — about chess or anything "
    "else — clearly and concisely. You have no tools, so answer from your own "
    "knowledge and say plainly when you are unsure. Reply in warm, natural prose."
)


class OpenChatSession:
    """An open, tool-free assistant conversation over a persistent Claude client.

    Implements :class:`~chess_coach.application.ports.open_chat.OpenChatPort`
    structurally: open it as an async context manager, then :meth:`stream` per turn.
    """

    def __init__(self, *, model: str = DEFAULT_MODEL, max_turns: int = 8) -> None:
        self._model = model
        self._max_turns = max_turns
        self._client: ClaudeSDKClient | None = None

    def _options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            model=self._model,
            system_prompt=_OPEN_CHAT_SYSTEM_PROMPT,
            allowed_tools=[],
            disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
            permission_mode="bypassPermissions",
            max_turns=self._max_turns,
            env=tracing.claude_env(),
        )

    async def __aenter__(self) -> OpenChatSession:
        self._client = ClaudeSDKClient(options=self._options())
        await self._client.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def stream(self, message: str) -> AsyncIterator[str]:
        """Send one user turn and yield the assistant's reply text as it arrives."""
        if self._client is None:
            raise RuntimeError("OpenChatSession used outside an `async with` block")
        await self._client.query(message)
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        yield block.text

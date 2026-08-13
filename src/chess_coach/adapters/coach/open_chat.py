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
    ResultMessage,
    TextBlock,
)

from chess_coach.adapters.coach.agent import DEFAULT_MODEL, _turn_attrs
from chess_coach.adapters.coach.prompts import OPEN_CHAT_SYSTEM_PROMPT
from chess_coach.adapters.observability import tracing

_OPEN_CHAT_SYSTEM_PROMPT = OPEN_CHAT_SYSTEM_PROMPT


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
        output_chunks: list[str] = []
        final = ""
        with tracing.turn_span(
            "coach.open_chat",
            _turn_attrs(self._model, None, "general_chat", None),
        ) as span:
            tracing.record_turn_context(
                span,
                input_value=message,
                provider="claude",
                system_prompt=_OPEN_CHAT_SYSTEM_PROMPT,
                skill_mode="none",
            )
            async for msg in self._client.receive_response():
                if isinstance(msg, AssistantMessage):
                    tracing.record_model_message(span, msg)
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text:
                            output_chunks.append(block.text)
                            yield block.text
                elif isinstance(msg, ResultMessage):
                    final = msg.result or ""
                    tracing.record_result(span, msg)
            tracing.record_output(span, final or "".join(output_chunks))
            tracing.mark_ok(span)

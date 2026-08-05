"""Container: builds adapters and injects them into use cases.

The wiring logic of the composition root — the one module permitted to depend on
every layer at once. Given validated :class:`Settings` it constructs the concrete
adapters (a pinned Stockfish analyzer, the offline opening book, the selected
coach provider), adapts the agent to the :class:`CoachPort`, and hands back the
wired coach behind a context manager so the engine subprocess is always torn
down.

Tracing-bullet slice: :func:`coach_service` yields the coach for the
coach-a-position path. As more use cases land they are assembled here the same
way; the CLI keeps dispatching to what this exposes, never constructing adapters
itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from chess_coach.adapters.coach.agent import AgentCoach
from chess_coach.adapters.coach.analysis import StockfishAnalyzer
from chess_coach.adapters.coach.chat import ChatSession
from chess_coach.adapters.coach.coach_port import AgentCoachAdapter
from chess_coach.adapters.coach.codex_agent import CodexChatSession, CodexCoach
from chess_coach.adapters.coach.open_chat import OpenChatSession
from chess_coach.adapters.coach.opening_book import OpeningBook
from chess_coach.adapters.coach.tablebase import Tablebase
from chess_coach.adapters.observability import tracing
from chess_coach.application.ports.chat import ChatCoachPort
from chess_coach.application.ports.coach import CoachPort
from chess_coach.application.ports.open_chat import OpenChatPort
from chess_coach.composition.config import Settings
from chess_coach.composition.providers import selected_model


def _configure_tracing(settings: Settings) -> None:
    """Wire the global tracer from settings (idempotent; a no-op when disabled)."""
    tracing.configure_tracing(
        enabled=settings.tracing_enabled,
        otlp_endpoint=settings.otlp_endpoint,
        native_telemetry=settings.native_telemetry,
        native_otlp_endpoint=settings.native_otlp_endpoint,
    )


@contextmanager
def coach_service(settings: Settings) -> Iterator[CoachPort]:
    """Yield a fully-wired :class:`CoachPort`, tearing the engine down after use."""
    _configure_tracing(settings)
    with StockfishAnalyzer(settings.stockfish_path, depth=settings.depth) as analyzer:
        book = OpeningBook()
        tablebase = Tablebase(settings.syzygy_path)
        if settings.provider == "claude":
            yield AgentCoachAdapter(
                AgentCoach(
                    analyzer, book, tablebase=tablebase, model=selected_model(settings)
                )
            )
            return
        # Codex takes the raw model (possibly None → its own CLI default).
        yield AgentCoachAdapter(
            CodexCoach(analyzer, book, tablebase=tablebase, model=settings.model)
        )


@asynccontextmanager
async def chat_service(settings: Settings) -> AsyncIterator[ChatCoachPort]:
    """Yield an open coaching conversation, tearing engine and client down after use.

    Unlike :func:`coach_service`, the session is held open across the whole
    conversation so the coach remembers the dialogue; the caller streams turns through
    it and the engine subprocess and agent client are closed on exit.
    """
    _configure_tracing(settings)
    with StockfishAnalyzer(settings.stockfish_path, depth=settings.depth) as analyzer:
        book = OpeningBook()
        tablebase = Tablebase(settings.syzygy_path)
        if settings.provider == "claude":
            async with ChatSession(
                analyzer, book, tablebase=tablebase, model=selected_model(settings)
            ) as session:
                yield session
            return
        # Codex takes the raw model (possibly None → its own CLI default).
        async with CodexChatSession(
            analyzer, book, tablebase=tablebase, model=settings.model
        ) as session:
            yield session


@asynccontextmanager
async def open_chat_service(settings: Settings) -> AsyncIterator[OpenChatPort]:
    """Yield an open, board-free assistant conversation, torn down after use.

    The counterpart to :func:`chat_service`: no engine and no tools, just a
    persistent Claude conversation the student can ask anything. It reuses the
    Claude model selected for the coach so the two voices match; there is no engine
    subprocess to manage here.
    """
    _configure_tracing(settings)
    model = selected_model(settings) if settings.provider == "claude" else None
    chat = OpenChatSession(model=model) if model is not None else OpenChatSession()
    async with chat as session:
        yield session

"""Coach tracing: no-op when off, correctly-shaped spans when on (no network)."""

from __future__ import annotations

from collections.abc import Iterator

import anyio
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from chess_coach.adapters.coach.analysis import PositionAnalysis
from chess_coach.adapters.coach.codex_agent import CodexCoach, CommandResult
from chess_coach.adapters.observability import tracing


@pytest.fixture(autouse=True)
def _restore_globals() -> Iterator[None]:
    """Snapshot and restore the module's global tracer state around each test."""
    saved = (tracing._tracer, tracing._enabled, dict(tracing._native_env))
    try:
        yield
    finally:
        tracing._tracer, tracing._enabled, tracing._native_env = (
            saved[0],
            saved[1],
            saved[2],
        )


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    """Install an in-memory tracer and hand back its exporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracing.use_tracer(provider.get_tracer("test"))
    yield exporter


class _FakeResult:
    """A stand-in for the SDK's ResultMessage carrying a turn's summary."""

    total_cost_usd = 0.0123
    duration_ms = 950
    duration_api_ms = 800
    num_turns = 3
    stop_reason = "end_turn"
    is_error = False
    usage = {"input_tokens": 1200, "output_tokens": 300}
    result = "You should play Rc8#."


def test_disabled_is_a_noop() -> None:
    tracing.use_tracer(None)
    assert tracing.is_enabled() is False
    assert tracing.claude_env() == {}
    with tracing.turn_span("coach.answer", {"chess.fen": "x"}) as span:
        with tracing.tool_span("tool.analyze_position", {"chess.fen": "x"}) as tool:
            tool.set_attribute("k", "v")
        tracing.record_result(span, _FakeResult())
    # No exporter, no provider — the point is simply that nothing raised.


def test_turn_and_tool_spans_nest(spans: InMemorySpanExporter) -> None:
    @tracing.trace_tool("analyze_position")
    async def fake_tool(args: dict[str, object]) -> dict[str, object]:
        return {"ok": True}

    async def run() -> None:
        attrs = {"chess.fen": "FEN", "coach.level": None}
        with tracing.turn_span("coach.answer", attrs):
            await fake_tool({"fen": "FEN", "move": "e2e4"})

    anyio.run(run)

    finished = {s.name: s for s in spans.get_finished_spans()}
    assert set(finished) == {"coach.answer", "tool.analyze_position"}

    turn = finished["coach.answer"]
    tool = finished["tool.analyze_position"]
    # The tool span is a child of the turn span.
    assert tool.parent is not None
    assert tool.parent.span_id == turn.context.span_id
    # None-valued attributes (level) are dropped, not sent as the string "None".
    assert "coach.level" not in turn.attributes
    assert tool.attributes["tool.name"] == "analyze_position"
    assert tool.attributes["chess.fen"] == "FEN"
    assert tool.attributes["chess.move"] == "e2e4"


def test_record_result_copies_cost_and_tokens(spans: InMemorySpanExporter) -> None:
    with tracing.turn_span("coach.answer", {"chess.fen": "FEN"}) as span:
        tracing.record_result(span, _FakeResult())

    (turn,) = spans.get_finished_spans()
    assert turn.attributes["coach.cost_usd"] == pytest.approx(0.0123)
    assert turn.attributes["coach.num_turns"] == 3
    assert turn.attributes["llm.token_count.prompt"] == 1200
    assert turn.attributes["llm.token_count.completion"] == 300
    assert turn.attributes["llm.token_count.total"] == 1500


def test_tool_span_records_exception(spans: InMemorySpanExporter) -> None:
    with (
        pytest.raises(ValueError),  # noqa: PT011 - the error's identity isn't the point
        tracing.tool_span("tool.analyze_position", {"chess.fen": "FEN"}),
    ):
        raise ValueError("bad fen")

    (tool,) = spans.get_finished_spans()
    assert tool.status.status_code.name == "ERROR"
    assert any(e.name == "exception" for e in tool.events)


class _StubAnalyzer:
    """A fake engine so the Codex trace test needs no Stockfish binary."""

    def analyze(self, fen: str) -> PositionAnalysis:
        return PositionAnalysis("e2e4", "e4", 25, None, "equal", "draw")


def _canned_codex(command: object, stdin: object) -> CommandResult:
    return CommandResult(
        returncode=0,
        stdout='```json\n{"best_move": "e2e4", "explanation": "Centre."}\n```',
        stderr="",
    )


def test_codex_provider_emits_nested_spans(spans: InMemorySpanExporter) -> None:
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    coach = CodexCoach(_StubAnalyzer(), runner=_canned_codex, model="gpt-5")

    coach.answer_sync(start, "best_move", level="beginner")

    finished = {s.name: s for s in spans.get_finished_spans()}
    assert set(finished) == {"coach.answer", "engine.ground_truth", "codex.exec"}
    turn = finished["coach.answer"]
    assert turn.attributes["coach.provider"] == "codex"
    # Both the engine and the Codex CLI spans hang off the turn span.
    for child in ("engine.ground_truth", "codex.exec"):
        assert finished[child].parent.span_id == turn.context.span_id


def test_native_env_is_off_until_configured() -> None:
    assert tracing.claude_env() == {}


def test_native_env_builder_and_base_derivation() -> None:
    assert (
        tracing._otlp_base("http://localhost:6006/v1/traces") == "http://localhost:6006"
    )
    assert tracing._otlp_base("http://collector:4318/") == "http://collector:4318"
    env = tracing._build_native_env("http://localhost:6006")
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:6006"

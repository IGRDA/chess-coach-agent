"""Coach tracing: no-op when off, correctly-shaped spans when on (no network)."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from chess_coach.adapters.coach.analysis import PositionAnalysis
from chess_coach.adapters.coach.codex_agent import CodexCoach, CommandResult
from chess_coach.adapters.observability import latency, tracing


def _attrs(span: ReadableSpan) -> Mapping[str, Any]:
    """Narrow the SDK's optional, scalar-only attribute type for test assertions."""
    assert span.attributes is not None
    return span.attributes


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


def test_latency_is_sampled_even_when_tracing_is_off() -> None:
    """The p50/p90 report must work without a backend — that is its whole point.

    Tracing can be switched off; the sampler cannot, so a coach run on a
    plain laptop still yields a latency distribution.
    """
    tracing.use_tracer(None)
    latency.reset()

    with (
        tracing.turn_span("coach.answer", {"chess.fen": "x"}),
        tracing.tool_span("tool.evaluate_move", {"chess.fen": "x"}),
    ):
        pass

    assert latency.SAMPLER.samples("coach.answer.latency_ms")
    assert latency.SAMPLER.samples("tool.evaluate_move.latency_ms")


def test_tokens_are_sampled_from_a_result(spans: InMemorySpanExporter) -> None:
    latency.reset()
    with tracing.turn_span("coach.answer", {}) as span:
        tracing.record_result(span, _FakeResult())

    assert latency.SAMPLER.samples("tokens.prompt") == [1200.0]
    assert latency.SAMPLER.samples("tokens.completion") == [300.0]
    assert latency.SAMPLER.samples("tokens.total") == [1500.0]


def test_usage_can_be_recorded_without_a_span() -> None:
    """Providers with no SDK ResultMessage (Codex) still report their usage."""
    latency.reset()
    tracing.record_usage(10, 5, 0.02)

    assert latency.SAMPLER.samples("tokens.total") == [15.0]
    assert latency.SAMPLER.samples("cost.usd") == [0.02]


def test_a_failing_turn_still_records_its_latency() -> None:
    """A timeout is a latency data point, not a hole in the distribution."""
    tracing.use_tracer(None)
    latency.reset()

    with pytest.raises(RuntimeError), tracing.turn_span("coach.answer", {}):
        raise RuntimeError("model exploded")

    assert len(latency.SAMPLER.samples("coach.answer.latency_ms")) == 1


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
    turn_attrs = _attrs(turn)
    tool_attrs = _attrs(tool)
    # The tool span is a child of the turn span.
    assert tool.parent is not None
    assert tool.parent.span_id == turn.context.span_id
    # None-valued attributes (level) are dropped, not sent as the string "None".
    assert "coach.level" not in turn_attrs
    assert tool_attrs["tool.name"] == "analyze_position"
    assert tool_attrs["chess.fen"] == "FEN"
    assert tool_attrs["chess.move"] == "e2e4"
    assert json.loads(tool_attrs["input.value"])["move"] == "e2e4"
    assert json.loads(tool_attrs["output.value"])["ok"] is True
    assert tool.status.status_code.name == "OK"


def test_turn_context_records_inline_skills_once(spans: InMemorySpanExporter) -> None:
    with tracing.turn_span("coach.chat", {}) as span:
        tracing.record_turn_context(
            span,
            input_value="Help me find a plan",
            provider="claude",
            system_prompt="Teach, then verify.",
            skills=["interactive-coach", "interactive-coach"],
            skill_mode="inline",
        )
        tracing.record_output(span, "Look at the open file first.")
        tracing.mark_ok(span)

    (turn,) = spans.get_finished_spans()
    attrs = _attrs(turn)
    assert attrs["coach.provider"] == "claude"
    assert attrs["coach.skills.available"] == ("interactive-coach",)
    assert attrs["coach.skills.loaded"] == ("interactive-coach",)
    assert attrs["input.value"] == "Help me find a plan"
    assert attrs["output.value"] == "Look at the open file first."
    assert [event.name for event in turn.events] == ["skill.loaded"]


def test_claude_message_records_exposed_reasoning_and_skill_load(
    spans: InMemorySpanExporter,
) -> None:
    message = SimpleNamespace(
        model="claude-test",
        stop_reason="tool_use",
        content=[
            SimpleNamespace(thinking="I should verify the position first."),
            SimpleNamespace(
                name="Skill",
                id="skill-call-1",
                input={"skill": "tactics-coach"},
            ),
        ],
    )
    with tracing.turn_span("coach.answer", {}) as span:
        tracing.record_turn_context(
            span,
            input_value="Find the tactic",
            provider="claude",
            skills=["tactics-coach"],
            skill_mode="dynamic",
        )
        tracing.record_model_message(span, message)
        tracing.mark_ok(span)

    (turn,) = spans.get_finished_spans()
    attrs = _attrs(turn)
    assert attrs["llm.model_name"] == "claude-test"
    assert attrs["coach.skills.loaded"] == ("tactics-coach",)
    assert [event.name for event in turn.events] == [
        "model.reasoning",
        "model.tool_choice",
        "skill.loaded",
    ]
    reasoning_attrs = turn.events[0].attributes
    assert reasoning_attrs is not None
    assert reasoning_attrs["reasoning.summary"] == "I should verify the position first."


def test_codex_jsonl_keeps_reasoning_thread_and_usage(
    spans: InMemorySpanExporter,
) -> None:
    events = [
        {"type": "thread.started", "thread_id": "thread-123"},
        {
            "type": "item.completed",
            "item": {"type": "reasoning", "text": "Compare forcing moves."},
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Play e4."},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 20,
                "reasoning_output_tokens": 8,
            },
        },
    ]
    jsonl = "\n".join(json.dumps(event) for event in events)

    with tracing.turn_span("coach.answer", {}) as turn:
        tracing.record_turn_context(
            turn,
            input_value="Analyze",
            provider="codex",
            skill_mode="not-configured",
        )
        with tracing.tool_span("codex.exec", {}) as llm:
            tracing.record_codex_events(llm, jsonl)
        tracing.mark_ok(turn)

    finished = {span.name: span for span in spans.get_finished_spans()}
    llm = finished["codex.exec"]
    attrs = _attrs(llm)
    assert attrs["codex.thread_id"] == "thread-123"
    assert attrs["llm.token_count.total"] == 120
    assert attrs["llm.token_count.cached"] == 40
    assert attrs["llm.token_count.reasoning"] == 8
    assert [event.name for event in llm.events] == ["model.reasoning"]
    reasoning_attrs = llm.events[0].attributes
    assert reasoning_attrs is not None
    assert reasoning_attrs["reasoning.summary"] == "Compare forcing moves."


def test_record_result_copies_cost_and_tokens(spans: InMemorySpanExporter) -> None:
    with tracing.turn_span("coach.answer", {"chess.fen": "FEN"}) as span:
        tracing.record_result(span, _FakeResult())

    (turn,) = spans.get_finished_spans()
    attrs = _attrs(turn)
    assert attrs["coach.cost_usd"] == pytest.approx(0.0123)
    assert attrs["coach.num_turns"] == 3
    assert attrs["llm.token_count.prompt"] == 1200
    assert attrs["llm.token_count.completion"] == 300
    assert attrs["llm.token_count.total"] == 1500


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
    commands: list[list[str]] = []

    def runner(command: object, stdin: object) -> CommandResult:
        assert isinstance(command, list)
        commands.append(command)
        return _canned_codex(command, stdin)

    coach = CodexCoach(_StubAnalyzer(), runner=runner, model="gpt-5")

    coach.answer_sync(start, "best_move", level="beginner")

    finished = {s.name: s for s in spans.get_finished_spans()}
    assert set(finished) == {"coach.answer", "engine.ground_truth", "codex.exec"}
    turn = finished["coach.answer"]
    attrs = _attrs(turn)
    assert attrs["coach.provider"] == "codex"
    assert attrs["coach.skills.mode"] == "inline"
    assert attrs["coach.skills.loaded"] == ("tactics-coach",)
    assert json.loads(attrs["input.value"])["task_type"] == "best_move"
    assert attrs["llm.system_prompt"]
    assert json.loads(attrs["output.value"])["best_move"] == "e2e4"
    assert turn.status.status_code.name == "OK"
    engine_input = json.loads(_attrs(finished["engine.ground_truth"])["input.value"])
    assert engine_input == {"fen": start, "candidate_move": None}
    assert "model_reasoning_summary=detailed" in commands[0]
    assert "hide_agent_reasoning=false" in commands[0]
    assert _attrs(finished["codex.exec"])["llm.reasoning_summary_mode"] == "detailed"
    # Both the engine and the Codex CLI spans hang off the turn span.
    assert turn.context is not None
    for child in ("engine.ground_truth", "codex.exec"):
        parent = finished[child].parent
        assert parent is not None
        assert parent.span_id == turn.context.span_id


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

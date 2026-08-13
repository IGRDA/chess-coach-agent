"""OpenTelemetry tracing for the coaching agent — a deep, opt-in module.

The whole product is organised around one Claude agent grounded in Stockfish. This
module makes a coaching turn *observable*: one span per turn (its model, cost,
tokens, latency and outcome) with a child span per in-process chess tool call (the
real Stockfish latency and the arguments it saw). Point it at any OTLP backend; the
network-free default is a local `arize-phoenix` UI at http://localhost:6006.

Two design decisions worth naming:

* **It is off by default and degrades to nothing.** When tracing is disabled — or
  OpenTelemetry is not installed at all — every entry point here is a cheap no-op, so
  the coach code can call it unconditionally and the domain stays dependency-free.
* **Tool spans nest under their turn explicitly.** The SDK invokes the in-process
  tools from its own task, so we carry the turn's OTel context in a
  :class:`~contextvars.ContextVar` and parent each tool span to it by hand rather than
  hoping context propagation crosses the task boundary.

Why the Claude Code subprocess needs its own wiring: :func:`claude_env` returns the
env that turns on the CLI's *native* telemetry (token/cost metrics and events emitted
from inside the subprocess, where the real model calls happen — a place Python-side
instrumentation cannot reach). Merge it into ``ClaudeAgentOptions(env=...)``.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import json
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from chess_coach.adapters.observability import latency

try:  # OpenTelemetry is an optional extra ([tracing]); absence means "no-op".
    # Only the trace *API* is needed to record spans; the SDK pipeline and the OTLP
    # exporter are imported lazily in configure_tracing so a caller that injects its
    # own tracer (tests) needs nothing more than the API.
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    _OTEL_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised only without the extra
    _OTEL_AVAILABLE = False

_SERVICE_NAME = "chess-coach"
_TRACER_NAME = "chess_coach.coach"
_ATTR_VALUE_LIMIT = 2000  # keep prompts/results from bloating spans

# The OTel context of the coaching turn currently in flight, so a tool span opened
# from the SDK's task can be parented to it explicitly. ``None`` outside a turn.
_run_ctx: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "chess_coach_run_ctx", default=None
)

_enabled = False
_tracer: Any = None
# Env that switches on the Claude Code subprocess's native telemetry; empty when off.
_native_env: dict[str, str] = {}


def configure_tracing(
    *,
    enabled: bool,
    otlp_endpoint: str,
    native_telemetry: bool = False,
    native_otlp_endpoint: str | None = None,
) -> bool:
    """Wire the global tracer once; return whether tracing is active afterwards.

    Idempotent and safe to call from every service construction: the first enabling
    call installs the provider, later calls are ignored. A no-op (returning ``False``)
    when disabled or when the ``[tracing]`` extra is not installed.

    ``otlp_endpoint`` is the full traces URL (Phoenix: ``…/v1/traces``).
    ``native_otlp_endpoint`` is the *base* the Claude Code subprocess exports its
    metrics/events to; when omitted it is derived from ``otlp_endpoint``.
    """
    global _enabled, _tracer, _native_env

    if not enabled or not _OTEL_AVAILABLE:
        return _enabled

    if _tracer is None:
        # Imported here, not at module load: the SDK + OTLP exporter are only needed
        # once someone actually turns tracing on. Flipping the flag without the
        # `[tracing]` extra degrades to a warning, never a crash.
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ModuleNotFoundError:
            import warnings

            warnings.warn(
                "Tracing is enabled but the OpenTelemetry SDK/exporter is missing; "
                "install the extra with `pip install -e '.[tracing]'`. Continuing "
                "without tracing.",
                RuntimeWarning,
                stacklevel=2,
            )
            return _enabled

        provider = TracerProvider(
            resource=Resource.create({"service.name": _SERVICE_NAME})
        )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
        )
        # Only set the global provider if nothing else has (tests install their own).
        if trace.get_tracer_provider().__class__.__name__ == "ProxyTracerProvider":
            trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(_TRACER_NAME)
        _enabled = True

    _native_env = (
        _build_native_env(native_otlp_endpoint or _otlp_base(otlp_endpoint))
        if native_telemetry
        else {}
    )
    return _enabled


def use_tracer(tracer: Any) -> None:
    """Install a specific tracer and mark tracing active (for tests)."""
    global _tracer, _enabled
    _tracer = tracer
    _enabled = tracer is not None


def is_enabled() -> bool:
    """Whether spans are being recorded right now."""
    return _enabled and _tracer is not None


def claude_env() -> dict[str, str]:
    """Env vars enabling the Claude Code subprocess's native telemetry (or empty)."""
    return dict(_native_env)


@contextlib.contextmanager
def turn_span(name: str, attributes: dict[str, Any]) -> Iterator[Any]:
    """Open the root span for one coaching turn; child tool spans nest under it.

    Yields the span (or a no-op) so the caller can attach the final
    :class:`ResultMessage` via :func:`record_result`.

    The wall-clock stopwatch runs whether or not spans are being exported: it is
    the only latency figure available for providers that report none of their own
    (Codex), and it is what :mod:`latency` builds the p50/p90 report from.
    """
    started = time.perf_counter()
    if not is_enabled():
        try:
            yield _NOOP_SPAN
        finally:
            _record_elapsed(_NOOP_SPAN, name, started)
        return

    span = _tracer.start_span(name, attributes=_clean_attrs(attributes))
    ctx = trace.set_span_in_context(span)
    token = _run_ctx.set(ctx)
    try:
        yield span
    except Exception as exc:  # noqa: BLE001 - record then re-raise
        _mark_error(span, exc)
        raise
    finally:
        _run_ctx.reset(token)
        _record_elapsed(span, name, started)
        span.end()


@contextlib.contextmanager
def tool_span(name: str, attributes: dict[str, Any]) -> Iterator[Any]:
    """Open a span for one in-process tool call, parented to the active turn."""
    started = time.perf_counter()
    if not is_enabled():
        try:
            yield _NOOP_SPAN
        finally:
            _record_elapsed(_NOOP_SPAN, name, started)
        return

    span = _tracer.start_span(
        name, context=_run_ctx.get(), attributes=_clean_attrs(attributes)
    )
    try:
        yield span
    except Exception as exc:  # noqa: BLE001 - record then re-raise
        _mark_error(span, exc)
        raise
    finally:
        _record_elapsed(span, name, started)
        span.end()


def _record_elapsed(span: Any, name: str, started: float) -> None:
    """Stamp the measured wall-clock latency on the span and into the sampler."""
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    latency.record(f"{name}.latency_ms", elapsed_ms)
    _set(span, "latency_ms", round(elapsed_ms, 3))


def trace_tool(
    tool_name: str,
) -> Callable[[Callable[[dict[str, Any]], Awaitable[Any]]], Callable[..., Any]]:
    """Decorate an in-process async chess tool so each call becomes a nested span.

    Wraps *under* the SDK's ``@tool`` decorator. Records the tool name, its FEN and
    (when present) the move(s) it was asked about; a no-op when tracing is off.
    """

    def decorate(
        fn: Callable[[dict[str, Any]], Awaitable[Any]],
    ) -> Callable[[dict[str, Any]], Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(args: dict[str, Any]) -> Any:
            with tool_span(f"tool.{tool_name}", _tool_attrs(tool_name, args)):
                return await fn(args)

        return wrapper

    return decorate


def record_usage(prompt: int | None, completion: int | None, cost: float | None) -> None:
    """Feed token counts and cost into the sampler, independent of any span.

    Providers that report usage without an SDK ``ResultMessage`` (Codex) call this
    directly, so the token report covers every provider rather than only Claude.
    """
    if isinstance(prompt, int):
        latency.record("tokens.prompt", float(prompt))
    if isinstance(completion, int):
        latency.record("tokens.completion", float(completion))
    if isinstance(prompt, int) and isinstance(completion, int):
        latency.record("tokens.total", float(prompt + completion))
    if isinstance(cost, (int, float)):
        latency.record("cost.usd", float(cost))


def record_result(span: Any, result: Any) -> None:
    """Copy the SDK ``ResultMessage`` summary (cost, tokens, latency) onto the span.

    Also mirrors the usage into the sampler so a run's token totals can be
    summarised in-process, with or without a tracing backend attached.
    """
    if result is None:
        return
    usage = getattr(result, "usage", None)
    if isinstance(usage, dict):
        record_usage(
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            getattr(result, "total_cost_usd", None),
        )
    if span is _NOOP_SPAN:
        return
    _set(span, "coach.cost_usd", getattr(result, "total_cost_usd", None))
    _set(span, "coach.duration_ms", getattr(result, "duration_ms", None))
    _set(span, "coach.duration_api_ms", getattr(result, "duration_api_ms", None))
    _set(span, "coach.num_turns", getattr(result, "num_turns", None))
    _set(span, "coach.stop_reason", getattr(result, "stop_reason", None))
    if getattr(result, "is_error", False):
        span.set_status(Status(StatusCode.ERROR))
    usage = getattr(result, "usage", None)
    if isinstance(usage, dict):
        prompt = usage.get("input_tokens")
        completion = usage.get("output_tokens")
        _set(span, "llm.token_count.prompt", prompt)
        _set(span, "llm.token_count.completion", completion)
        if isinstance(prompt, int) and isinstance(completion, int):
            _set(span, "llm.token_count.total", prompt + completion)
    output = getattr(result, "result", None)
    if output:
        _set(span, "output.value", _truncate(str(output)))


# --- internals ---------------------------------------------------------------


def _build_native_env(base_endpoint: str) -> dict[str, str]:
    """Env that turns on Claude Code's own OTLP metrics/events export."""
    return {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": base_endpoint,
    }


def _otlp_base(traces_endpoint: str) -> str:
    """Derive the OTLP base URL from a full traces URL (strip a trailing /v1/traces)."""
    return (
        traces_endpoint[: -len("/v1/traces")]
        if (traces_endpoint.endswith("/v1/traces"))
        else traces_endpoint.rstrip("/")
    )


def _tool_attrs(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "openinference.span.kind": "TOOL",
        "tool.name": tool_name,
    }
    if isinstance(args, dict):
        if args.get("fen"):
            attrs["chess.fen"] = str(args["fen"])
        if args.get("move"):
            attrs["chess.move"] = str(args["move"])
        if args.get("moves"):
            attrs["chess.moves"] = _truncate(json.dumps(args["moves"], default=str))
    return attrs


def _clean_attrs(attributes: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None`` values OTel would reject and truncate long strings."""
    clean: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        clean[key] = _truncate(value) if isinstance(value, str) else value
    return clean


def _truncate(value: str) -> str:
    return value if len(value) <= _ATTR_VALUE_LIMIT else value[:_ATTR_VALUE_LIMIT] + "…"


def _set(span: Any, key: str, value: Any) -> None:
    if value is not None:
        span.set_attribute(key, value)


def _mark_error(span: Any, exc: BaseException) -> None:
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)))


class _NoopSpan:
    """A span that swallows every call, for the disabled / uninstalled path."""

    def set_attribute(self, *_a: Any, **_k: Any) -> None: ...
    def set_status(self, *_a: Any, **_k: Any) -> None: ...
    def record_exception(self, *_a: Any, **_k: Any) -> None: ...
    def add_event(self, *_a: Any, **_k: Any) -> None: ...
    def end(self, *_a: Any, **_k: Any) -> None: ...


_NOOP_SPAN = _NoopSpan()

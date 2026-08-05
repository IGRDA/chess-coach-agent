# Observability: tracing the coaching agent

The coach is one Claude agent grounded in Stockfish. Tracing makes each coaching
turn visible: **one span per turn** (model, cost, tokens, latency, outcome) with a
**child span per in-process chess tool call** (the real engine latency and the FEN it
saw). Spans are emitted as standard OpenTelemetry OTLP, so any backend works; the
default target is a local, network-free [Arize Phoenix](https://phoenix.arize.com/).

Everything lives in the adapters layer (`adapters/observability/tracing.py`); the
domain and use cases stay dependency-free. It is **off by default** and degrades to a
cheap no-op when disabled or when the extra is not installed.

## Why not "just auto-instrument the SDK"

`claude-agent-sdk` runs the Claude Code CLI in a **subprocess**; the model calls
happen there, not in a Python `anthropic` client. So the usual auto-instrumentation
libraries (OpenLLMetry, OpenInference auto-patching, MLflow autolog) see nothing. We
instead trace at two places we *do* control:

1. **Manual spans** around `AgentCoach.answer` / `teach` and `ChatSession.stream`, plus
   the six in-process chess tools. This is the trace waterfall you read in Phoenix.
2. **Native Claude Code telemetry** (optional): env vars that switch on the CLI's own
   token/cost metrics and events, emitted from inside the subprocess. The SDK also
   propagates the active `TRACEPARENT` into the subprocess, so those link back to the
   turn span.

## Quickstart (Phoenix, local)

```bash
pip install -e '.[tracing]'          # opentelemetry sdk + otlp exporter + phoenix
phoenix serve                         # trace UI + collector at http://localhost:6006

# in another shell — enable tracing and run the coach as usual
export CHESS_COACH_TRACING_ENABLED=1
chess-coach coach "<FEN>" ...
```

Open <http://localhost:6006> and watch turns appear, each expandable to its tool
calls. Spans use OpenInference span kinds (`AGENT` / `TOOL`) so Phoenix categorises
them automatically.

## Settings

All env-only (a dev/ops concern; not persisted in `config.toml`):

| Env var | Default | Meaning |
| --- | --- | --- |
| `CHESS_COACH_TRACING_ENABLED` | `false` | Emit per-turn + per-tool spans. |
| `CHESS_COACH_OTLP_ENDPOINT` | `http://localhost:6006/v1/traces` | Full OTLP traces URL. |
| `CHESS_COACH_NATIVE_TELEMETRY` | `false` | Also turn on the Claude Code subprocess's own metrics/events. |
| `CHESS_COACH_NATIVE_OTLP_ENDPOINT` | derived from the traces URL | Base OTLP endpoint for that native telemetry. |

Point at any other backend by changing `CHESS_COACH_OTLP_ENDPOINT` (e.g. a
self-hosted Langfuse or an OpenTelemetry Collector).

**Note on native telemetry:** it emits *metrics and events*, not spans. Phoenix is
trace-focused, so send native telemetry to a metrics-capable backend (an OTel
Collector, Grafana) via `CHESS_COACH_NATIVE_OTLP_ENDPOINT` when you enable it.

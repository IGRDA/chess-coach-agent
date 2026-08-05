# AGENTS.md — chess-coach

Operating guide for AI agents (the Claude coach agent, and coding agents) working
in this repository. This is a **skeleton**: files currently contain only interface
descriptions (module docstrings), no implementation.

## What this project is

An agentic chess coach. A Claude agent is the coaching brain; **Stockfish is the
source of chess truth**, invoked by the agent as a CLI tool rather than embedded.
Humans use the CLI; the agent and humans share the same underlying use cases.

## Architecture (respect the dependency rule)

Dependencies point **inward**. When implementing, never import outward.

```
interface (CLI) ─┐
adapters        ─┼─►  application (use cases + ports)  ─►  domain
composition     ─┘
```

- `src/chess_coach/domain` — pure model; depends on nothing external.
- `src/chess_coach/application` — use cases + `ports/` (abstract interfaces).
- `src/chess_coach/adapters` — implement ports (Stockfish, Claude, sources, SQLite).
- `src/chess_coach/interface/cli` — thin delivery; argv → use case → presenter.
- `src/chess_coach/composition` — the only place that wires concretes together.

## How the coach agent uses the engine

The agent consults Stockfish through the CLI, **not** by calling Python directly:

```
chess-coach engine --fen "<FEN>" [--depth N | --movetime MS]
```

This returns the evaluation and best move in a script-friendly form. The agent
skills under `skills/` describe the higher-level tasks built on this command.

## Skills

Agent-facing capabilities live in `skills/<name>/SKILL.md` (Claude Agent SDK
convention). Each describes when to use it and which CLI commands it calls.

## Guardrails

- Keep engine truth (Stockfish) and narration (the agent) separate: the agent
  explains evaluations, it does not invent them.
- Do not leak third-party types across ports; translate to domain objects at the
  boundary.
- Coaching tone/level is always an explicit parameter, never hard-coded.

## Conventions for coding agents

- Tooling: `uv`. Lint/format `ruff`, types `mypy --strict`, tests `pytest`.
- Before implementing a module, read its docstring — it states the module's
  single responsibility and contract. Preserve it.
- Add behaviour behind existing ports; don't bypass the composition root.

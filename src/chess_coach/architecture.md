# Architecture

`chess-coach` is an **agentic chess coaching application** built as a clean
architecture: a small, pure core surrounded by rings of increasingly
technology-specific code, with **all dependencies pointing inward**.

## The rings (inner → outer)

| Ring | Package | Responsibility | May depend on |
|------|---------|----------------|---------------|
| Domain | `domain/` | The chess-coaching model: positions, moves, games, evaluations, players, weaknesses, drills, lessons, errors. Pure Python. | nothing |
| Application | `application/` | Use cases (coaching workflows) and the **ports** they depend on. | domain |
| Adapters | `adapters/` | Concrete implementations of ports: Stockfish (UCI), Claude (Agent SDK), PGN/Lichess/Chess.com sources, SQLite repositories. | application, domain |
| Interface | `interface/` | Delivery — the CLI. Translates argv → use case → rendered output. | application, domain |
| Composition | `composition/` | The composition root. Reads config, builds adapters, injects them into use cases. | everything |

The **dependency rule**: an inner ring never imports an outer ring. The domain
knows nothing of Stockfish, Claude, HTTP or SQL. The use cases know only the
domain and their own ports. Concrete technology is chosen exactly once, in
`composition/`.

## Ports & adapters (the seams)

Each port is a **deep, narrow interface**: a handful of operations stated in
domain terms, hiding a large, messy implementation.

| Port (application) | Adapter(s) (adapters) | Hidden complexity |
|--------------------|-----------------------|-------------------|
| `EnginePort` | `engine/stockfish.py` | UCI protocol, engine process lifecycle, search limits |
| `CoachPort` | `coach/agent.py`, `coach/codex_agent.py` | Provider SDK/CLI, prompt rendering, tool/skill wiring, streaming |
| `GameSourcePort` | `sources/pgn.py`, `sources/lichess.py`, `sources/chesscom.py` | file/format parsing, HTTP, pagination, rate limits |
| `PositionParserPort` | `sources/fen.py` | FEN parsing and legality |
| `GameRepository` / `ProgressRepository` / `DrillRepository` | `persistence/sqlite/*` | SQL, transactions, row↔aggregate mapping |
| `ClockPort` | (system clock adapter) | wall-clock time, for deterministic tests |

## Prompt ownership

Production prompt wording has one editing surface:
`src/chess_coach/adapters/coach/prompts.py`. It contains the Claude and Codex system
prompts, task briefs, and presentation-only renderers. Provider adapters import those
assets and retain responsibility for tool calls, engine grounding, tracing, and model
execution.

Provider-neutral coaching skills live under `.agents/skills/`. A shared loader selects
one method for each task; the Claude adapter maps its logical capabilities to MCP
tools, while the Codex adapter activates the same skill against precomputed engine
facts. `.claude/skills` is only a compatibility symlink for native Claude discovery.
Skills are not the home for standing runtime prompts. Prompts used only to generate
or grade evaluation data remain under `evals/`.

## The engine is a tool the agent calls

Stockfish is not embedded in the agent. It is exposed as a CLI command
(`chess-coach engine …`) that the Claude coach invokes as a tool/skill. This keeps
objective evaluation (the engine) cleanly separated from narration (the agent) and
lets both humans and the agent reach the same engine through one contract.

## Design principles applied

- **A Philosophy of Software Design** — deep modules behind narrow interfaces; no
  shallow pass-throughs; errors defined out of existence where possible.
- **Clean Architecture** — the dependency rule; ports declared inward, implemented
  outward; a single composition root.
- **The Pragmatic Programmer** — DRY, orthogonality, decoupling via ports &
  adapters, design by contract.

## Data flow (example: analyse a game)

```
CLI `analyze`  →  AnalyzeGame use case
                    ├─ GameRepository.load        (SQLite adapter)
                    ├─ EnginePort.analyse         (Stockfish adapter)
                    ├─ CoachPort.summarise        (Claude adapter)
                    └─ ProgressRepository.save     (SQLite adapter)
                  →  result DTO  →  presenter  →  rendered review
```

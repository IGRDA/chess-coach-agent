# chess-coach

## Setup

```bash
uv sync --dev
uv run pre-commit install
```

## First run

```bash
uv run chess-coach setup
uv run chess-coach provider status
uv run chess-coach doctor
```

Switch providers at any time:

```bash
uv run chess-coach provider use claude
uv run chess-coach provider use codex
```

The active provider supplies the coaching narration; Stockfish remains the source
of chess truth.

## Development

```bash
uv run ruff check .
uv run ruff format .
uv run mypy .
uv run pytest --cov
```

"""Configuration: the single source of runtime settings.

Resolves everything the composition root needs to wire the app from the
environment, in one validated value object, so no other module reads
configuration directly. Missing or invalid settings fail fast here, before any
adapter is constructed.

Tracing-bullet slice: the coach-a-position path needs a model id, an optional
explicit Stockfish binary path, and the engine search depth. Database location and
online-source tokens join this object as their use cases land.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal, cast

from pydantic_settings import BaseSettings, SettingsConfigDict

from chess_coach.adapters.coach.analysis import DEFAULT_DEPTH

ProviderName = Literal["claude", "codex"]

_CONFIG_PATH_ENV = "CHESS_COACH_CONFIG_PATH"
_ENV_PREFIX = "CHESS_COACH_"
_CONFIG_FIELDS = {
    "provider": "PROVIDER",
    "model": "MODEL",
    "stockfish_path": "STOCKFISH_PATH",
    "depth": "DEPTH",
    "syzygy_path": "SYZYGY_PATH",
}


class Settings(BaseSettings):
    """Resolved runtime configuration, loaded from the environment."""

    model_config = SettingsConfigDict(env_prefix="CHESS_COACH_", extra="ignore")

    # The active coaching provider. Env: CHESS_COACH_PROVIDER.
    provider: ProviderName = "claude"
    # The coaching model. Env: CHESS_COACH_MODEL. When omitted, each provider uses
    # its own default.
    model: str | None = None
    # Explicit Stockfish binary; when unset the adapter searches $STOCKFISH_PATH
    # then $PATH. Env: CHESS_COACH_STOCKFISH_PATH.
    stockfish_path: str | None = None
    # Engine search depth. Env: CHESS_COACH_DEPTH.
    depth: int = DEFAULT_DEPTH
    # Optional Syzygy tablebase directory for exact endgame truth; when unset the
    # endgame tool degrades gracefully. Env: CHESS_COACH_SYZYGY_PATH.
    syzygy_path: str | None = None
    # Observability (env-only; a dev/ops concern, not persisted in config.toml).
    # Emit OpenTelemetry spans for each coaching turn. Env: CHESS_COACH_TRACING_ENABLED.
    tracing_enabled: bool = True
    # Full OTLP traces URL spans are exported to; the default is a local Arize Phoenix.
    # Env: CHESS_COACH_OTLP_ENDPOINT.
    otlp_endpoint: str = "http://localhost:6006/v1/traces"
    # Also switch on the Claude Code subprocess's own token/cost telemetry. Needs a
    # metrics-capable OTLP backend. Env: CHESS_COACH_NATIVE_TELEMETRY.
    native_telemetry: bool = False
    # Base OTLP endpoint for that native telemetry; derived from otlp_endpoint when
    # unset. Env: CHESS_COACH_NATIVE_OTLP_ENDPOINT.
    native_otlp_endpoint: str | None = None


def load_settings() -> Settings:
    """Load and validate settings from user config, then environment overrides."""
    data = _read_user_config()
    data.update(_explicit_env_values())
    return Settings(**cast(dict[str, Any], data))


def config_path() -> Path:
    """Return the user-level configuration path, test-overridable by env."""
    override = os.environ.get(_CONFIG_PATH_ENV)
    if override:
        return Path(override).expanduser()
    root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".config"
    return base / "chess-coach" / "config.toml"


def save_provider(provider: ProviderName) -> Path:
    """Persist the active provider in the user config file."""
    data = _read_user_config()
    data["provider"] = provider
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_config(data), encoding="utf-8")
    return path


def _read_user_config() -> dict[str, object]:
    path = config_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in _CONFIG_FIELDS}


def _explicit_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for field, suffix in _CONFIG_FIELDS.items():
        key = f"{_ENV_PREFIX}{suffix}"
        if key in os.environ:
            values[field] = os.environ[key]
    return values


def _format_config(data: dict[str, object]) -> str:
    lines: list[str] = []
    for key in _CONFIG_FIELDS:
        if key not in data or data[key] is None:
            continue
        value = data[key]
        rendered = str(value) if isinstance(value, int) else f'"{str(value)}"'
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + ("\n" if lines else "")

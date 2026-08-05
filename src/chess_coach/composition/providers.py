"""Provider registry and diagnostics for coach backends.

The composition root owns provider selection: application use cases depend only on
ports, while this module knows which concrete adapter and external CLI belong to
each configured provider. It also provides small auth/health checks for the
terminal setup commands without letting those checks leak into the domain.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from chess_coach.adapters.coach.agent import DEFAULT_MODEL as DEFAULT_CLAUDE_MODEL
from chess_coach.adapters.coach.analysis import EngineUnavailableError, find_stockfish
from chess_coach.composition.config import ProviderName, Settings

# Shown for `doctor`/`provider status` when no model is explicitly configured. Codex
# has no app-forced default — it uses its own CLI config — so we say so rather than
# print a model id we do not actually request.
_CODEX_DEFAULT_LABEL = "codex default (~/.codex/config.toml)"

_AUTH_STATUS_COMMANDS: dict[ProviderName, list[str]] = {
    "claude": ["claude", "auth", "status"],
    "codex": ["codex", "login", "status"],
}

_AUTH_LOGIN_COMMANDS: dict[ProviderName, list[str]] = {
    "claude": ["claude", "auth", "login"],
    "codex": ["codex", "login"],
}


@dataclass(frozen=True)
class CommandResult:
    """A small, test-friendly subprocess result."""

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Check:
    """One setup or doctor check."""

    ok: bool
    detail: str


CommandRunner = Callable[[Sequence[str], bool], CommandResult]


def selected_model(settings: Settings) -> str:
    """Return the explicit model, or a label for the provider's own default."""
    if settings.model:
        return settings.model
    if settings.provider == "codex":
        return _CODEX_DEFAULT_LABEL
    return DEFAULT_CLAUDE_MODEL


def auth_status(provider: ProviderName, runner: CommandRunner | None = None) -> Check:
    """Check whether the provider's terminal auth appears ready."""
    command = _AUTH_STATUS_COMMANDS[provider]
    if shutil.which(command[0]) is None:
        return Check(False, f"{command[0]} command not found")
    result = (runner or run_command)(command, True)
    detail = _detail(result) or "authenticated"
    return Check(result.returncode == 0, detail)


def login_provider(
    provider: ProviderName, runner: CommandRunner | None = None
) -> CommandResult:
    """Run the provider's interactive login command."""
    return (runner or run_command)(_AUTH_LOGIN_COMMANDS[provider], False)


def stockfish_status(settings: Settings) -> Check:
    """Check whether Stockfish can be located."""
    if settings.stockfish_path:
        configured = Path(settings.stockfish_path).expanduser()
        if configured.exists() or shutil.which(settings.stockfish_path):
            return Check(True, str(configured))
        return Check(False, f"configured path not found: {configured}")
    try:
        return Check(True, find_stockfish())
    except EngineUnavailableError as exc:
        return Check(False, str(exc))


def run_command(command: Sequence[str], capture: bool) -> CommandResult:
    """Run a command for auth checks or interactive login."""
    completed = subprocess.run(
        list(command),
        capture_output=capture,
        text=True,
        check=False,
    )
    return CommandResult(
        completed.returncode,
        completed.stdout or "",
        completed.stderr or "",
    )


def _detail(result: CommandResult) -> str:
    text = result.stdout.strip() or result.stderr.strip()
    if not text:
        return ""
    return text.splitlines()[0]

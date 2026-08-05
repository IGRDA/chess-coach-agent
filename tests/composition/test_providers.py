"""Provider registry and diagnostic checks."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from chess_coach.composition import providers
from chess_coach.composition.config import Settings
from chess_coach.composition.providers import CommandResult


def test_selected_model_labels_codex_cli_default() -> None:
    # Codex has no app-forced model; unset means "defer to the Codex CLI's own config".
    assert "codex default" in providers.selected_model(Settings(provider="codex"))


def test_selected_model_uses_claude_default() -> None:
    assert providers.selected_model(Settings(provider="claude")).startswith("claude-")


def test_selected_model_prefers_explicit_model() -> None:
    settings = Settings(provider="codex", model="gpt-test")
    assert providers.selected_model(settings) == "gpt-test"


def test_auth_status_reports_missing_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chess_coach.composition.providers.shutil.which", lambda _name: None
    )

    check = providers.auth_status("codex")

    assert not check.ok
    assert "codex command not found" in check.detail


def test_auth_status_runs_provider_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], bool]] = []

    def fake_runner(command: Sequence[str], capture: bool) -> CommandResult:
        calls.append((list(command), capture))
        return CommandResult(0, "Logged in\n", "")

    monkeypatch.setattr(
        "chess_coach.composition.providers.shutil.which", lambda _name: "/bin/tool"
    )

    check = providers.auth_status("claude", runner=fake_runner)

    assert check.ok
    assert check.detail == "Logged in"
    assert calls == [(["claude", "auth", "status"], True)]


def test_login_provider_runs_interactive_command() -> None:
    calls: list[tuple[list[str], bool]] = []

    def fake_runner(command: Sequence[str], capture: bool) -> CommandResult:
        calls.append((list(command), capture))
        return CommandResult(0, "", "")

    result = providers.login_provider("codex", runner=fake_runner)

    assert result.returncode == 0
    assert calls == [(["codex", "login"], False)]


def test_stockfish_status_reports_bad_configured_path() -> None:
    check = providers.stockfish_status(
        Settings(provider="claude", stockfish_path="/definitely/not/stockfish")
    )

    assert not check.ok
    assert "configured path not found" in check.detail

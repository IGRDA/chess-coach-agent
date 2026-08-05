"""Provider setup and diagnostic CLI tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from chess_coach.composition.providers import Check, CommandResult
from chess_coach.interface.cli.app import app

runner = CliRunner()


def test_provider_use_writes_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"

    result = runner.invoke(
        app,
        ["provider", "use", "codex"],
        env={"CHESS_COACH_CONFIG_PATH": str(path)},
    )

    assert result.exit_code == 0, result.output
    assert 'provider = "codex"' in path.read_text(encoding="utf-8")
    assert "Active provider: codex" in result.output


def test_setup_writes_provider_without_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    monkeypatch.setattr(
        "chess_coach.interface.cli.app.auth_status",
        lambda _provider: Check(True, "ready"),
    )
    monkeypatch.setattr(
        "chess_coach.interface.cli.app.stockfish_status",
        lambda _settings: Check(True, "/usr/bin/stockfish"),
    )

    result = runner.invoke(
        app,
        ["setup", "--provider", "codex", "--no-login"],
        env={"CHESS_COACH_CONFIG_PATH": str(path)},
    )

    assert result.exit_code == 0, result.output
    assert 'provider = "codex"' in path.read_text(encoding="utf-8")
    assert "Provider auth: OK - ready" in result.output


def test_provider_status_renders_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    path.write_text('provider = "codex"\nmodel = "gpt-test"\n', encoding="utf-8")
    monkeypatch.setattr(
        "chess_coach.interface.cli.app.auth_status",
        lambda _provider: Check(False, "not logged in"),
    )
    monkeypatch.setattr(
        "chess_coach.interface.cli.app.stockfish_status",
        lambda _settings: Check(True, "/usr/bin/stockfish"),
    )

    result = runner.invoke(
        app,
        ["provider", "status"],
        env={"CHESS_COACH_CONFIG_PATH": str(path)},
    )

    assert result.exit_code == 0, result.output
    assert "Provider: codex" in result.output
    assert "Model: gpt-test" in result.output
    assert "Provider auth: FAIL - not logged in" in result.output


def test_doctor_exits_nonzero_when_a_check_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    path.write_text('provider = "claude"\n', encoding="utf-8")
    monkeypatch.setattr(
        "chess_coach.interface.cli.app.auth_status",
        lambda _provider: Check(True, "ready"),
    )
    monkeypatch.setattr(
        "chess_coach.interface.cli.app.stockfish_status",
        lambda _settings: Check(False, "missing"),
    )

    result = runner.invoke(
        app,
        ["doctor"],
        env={"CHESS_COACH_CONFIG_PATH": str(path)},
    )

    assert result.exit_code == 1
    assert "Stockfish: FAIL - missing" in result.output


def test_provider_login_reports_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    path.write_text('provider = "claude"\n', encoding="utf-8")
    monkeypatch.setattr(
        "chess_coach.interface.cli.app.login_provider",
        lambda _provider: CommandResult(1, "", "no auth"),
    )

    result = runner.invoke(
        app,
        ["provider", "login"],
        env={"CHESS_COACH_CONFIG_PATH": str(path)},
    )

    assert result.exit_code == 1
    assert "Login failed: no auth" in result.output

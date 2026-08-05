"""Provider configuration loading and persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from chess_coach.composition.config import load_settings, save_provider
from chess_coach.composition.providers import selected_model


def _use_config(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setenv("CHESS_COACH_CONFIG_PATH", str(path))
    for name in (
        "CHESS_COACH_PROVIDER",
        "CHESS_COACH_MODEL",
        "CHESS_COACH_STOCKFISH_PATH",
        "CHESS_COACH_DEPTH",
        "CHESS_COACH_SYZYGY_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_claude_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_config(monkeypatch, tmp_path / "missing.toml")

    settings = load_settings()

    assert settings.provider == "claude"
    assert selected_model(settings).startswith("claude-")


def test_reads_provider_from_user_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    _use_config(monkeypatch, path)
    path.write_text('provider = "codex"\n', encoding="utf-8")

    settings = load_settings()

    assert settings.provider == "codex"
    assert "codex default" in selected_model(settings)


def test_environment_overrides_user_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    _use_config(monkeypatch, path)
    path.write_text('provider = "claude"\nmodel = "claude-test"\n', encoding="utf-8")
    monkeypatch.setenv("CHESS_COACH_PROVIDER", "codex")
    monkeypatch.setenv("CHESS_COACH_MODEL", "gpt-test")

    settings = load_settings()

    assert settings.provider == "codex"
    assert selected_model(settings) == "gpt-test"


def test_save_provider_preserves_existing_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    _use_config(monkeypatch, path)
    path.write_text('model = "custom-model"\n', encoding="utf-8")

    saved = save_provider("codex")

    assert saved == path
    settings = load_settings()
    assert settings.provider == "codex"
    assert settings.model == "custom-model"


def test_invalid_provider_fails_fast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    _use_config(monkeypatch, path)
    path.write_text('provider = "bad"\n', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_settings()

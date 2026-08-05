"""CLI command tests.

Drives the terminal app end-to-end with a fake coach injected in place of the
real Stockfish+Claude service, so the whole tracing bullet — argument parsing,
dispatch to the CoachPosition use case, rendering, and exit-code mapping — is
exercised fast and network-free. The container's coach factory is monkeypatched
to yield the fake, which is exactly the seam the composition root exists to
provide.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from chess_coach.application.dto import CoachingRequest, CoachingResult
from chess_coach.application.ports.coach import CoachPort
from chess_coach.interface.cli.app import app

from ..conftest import SCHOLARS_FEN, START_FEN, FakeCoach

runner = CliRunner()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> FakeCoach:
    """Patch the composition root so the CLI dispatches to a fake coach."""
    coach = FakeCoach()

    @contextmanager
    def fake_service(settings: object) -> Iterator[CoachPort]:
        yield coach

    monkeypatch.setattr("chess_coach.interface.cli.app.coach_service", fake_service)
    return coach


def test_coach_command_renders_answer(wired: FakeCoach) -> None:
    result = runner.invoke(app, ["coach", SCHOLARS_FEN])

    assert result.exit_code == 0, result.output
    assert "f3f7" in result.output
    assert "Scholar's Mate" in result.output


def test_coach_command_forwards_task_and_level(wired: FakeCoach) -> None:
    result = runner.invoke(
        app, ["coach", SCHOLARS_FEN, "--task", "eval_bucket", "--level", "beginner"]
    )

    assert result.exit_code == 0, result.output
    assert wired.calls == [
        CoachingRequest(fen=SCHOLARS_FEN, task="eval_bucket", level="beginner")
    ]


def test_coach_command_defaults_to_best_move(wired: FakeCoach) -> None:
    runner.invoke(app, ["coach", START_FEN])

    assert wired.calls[0].task == "best_move"
    assert wired.calls[0].level is None


def test_unknown_task_exits_nonzero_without_calling_coach(wired: FakeCoach) -> None:
    result = runner.invoke(app, ["coach", START_FEN, "--task", "tablebase"])

    assert result.exit_code != 0
    assert wired.calls == []
    assert "tablebase" in result.output


def test_tui_exits_engine_unavailable_when_stockfish_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from chess_coach.adapters.coach.analysis import EngineUnavailableError

    @contextmanager
    def broken_service(settings: object) -> Iterator[CoachPort]:
        raise EngineUnavailableError("stockfish not found")
        yield  # pragma: no cover - unreachable, marks this a generator

    launched = False

    def fake_run(**kwargs: object) -> None:
        nonlocal launched
        launched = True

    monkeypatch.setattr("chess_coach.interface.cli.app.coach_service", broken_service)
    monkeypatch.setattr("chess_coach.interface.tui.app.run", fake_run)

    result = runner.invoke(app, ["tui"])

    assert result.exit_code == 3
    assert "stockfish" in result.output
    assert launched is False


def test_tui_launches_the_app_when_the_engine_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def ok_service(settings: object) -> Iterator[CoachPort]:
        yield FakeCoach()

    launched = False

    def fake_run(**kwargs: object) -> None:
        nonlocal launched
        launched = True

    monkeypatch.setattr("chess_coach.interface.cli.app.coach_service", ok_service)
    monkeypatch.setattr("chess_coach.interface.tui.app.run", fake_run)

    result = runner.invoke(app, ["tui"])

    assert result.exit_code == 0, result.output
    assert launched is True


def test_invalid_fen_exits_nonzero(wired: FakeCoach) -> None:
    wired.result = CoachingResult(  # never reached; the adapter would reject first
        best_move=None, eval_bucket=None, result=None, explanation=""
    )

    def reject(request: CoachingRequest) -> CoachingResult:
        from chess_coach.domain.errors import InvalidPositionError

        raise InvalidPositionError("not a legal position: 'garbage'")

    wired.coach = reject  # type: ignore[method-assign]

    result = runner.invoke(app, ["coach", "garbage"])

    assert result.exit_code != 0
    assert "legal position" in result.output

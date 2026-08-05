"""Codex provider adapter tests with a fake CLI runner."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from chess_coach.adapters.coach.agent import CoachAgentError
from chess_coach.adapters.coach.analysis import PositionAnalysis
from chess_coach.adapters.coach.codex_agent import (
    CodexChatSession,
    CodexCoach,
    CommandResult,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class FakeAnalyzer:
    """Returns a stable opening-position analysis."""

    def analyze(self, fen: str) -> PositionAnalysis:
        assert fen == START_FEN
        return PositionAnalysis(
            best_move_uci="e2e4",
            best_move_san="e4",
            cp=20,
            mate=None,
            bucket="equal",
            result="draw",
        )


class FakeRunner:
    """Captures the Codex command and writes the requested final-message file."""

    def __init__(self, response: str, returncode: int = 0) -> None:
        self.response = response
        self.returncode = returncode
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, command: Sequence[str], stdin: str) -> CommandResult:
        args = list(command)
        self.calls.append((args, stdin))
        if self.returncode == 0:
            output = Path(args[args.index("--output-last-message") + 1])
            output.write_text(self.response, encoding="utf-8")
        return CommandResult(self.returncode, "", "codex failed")


def test_codex_coach_runs_cli_and_grounds_best_move() -> None:
    runner = FakeRunner(
        'Coach text.\n```json\n{"best_move": "h2h4", "eval_bucket": null, '
        '"result": null, "explanation": "Take the center."}\n```'
    )
    coach = CodexCoach(FakeAnalyzer(), model="gpt-test", runner=runner)

    answer = coach.answer_sync(START_FEN, "best_move", level="beginner")

    command, prompt = runner.calls[0]
    assert command[:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert "gpt-test" in command
    assert "Engine-grounded facts" in prompt
    assert '"best_move_uci": "e2e4"' in prompt
    assert answer.best_move == "e2e4"
    assert answer.explanation == "Take the center."


def test_codex_omits_model_flag_when_unset() -> None:
    # With no explicit model, defer to the Codex CLI's own default — never force one.
    runner = FakeRunner('```json\n{"best_move": "e2e4", "explanation": "x"}\n```')
    coach = CodexCoach(FakeAnalyzer(), runner=runner)

    coach.answer_sync(START_FEN, "best_move")

    command, _ = runner.calls[0]
    assert "--model" not in command


def test_codex_coach_grounds_eval_bucket() -> None:
    runner = FakeRunner(
        '```json\n{"best_move": null, "eval_bucket": "winning", '
        '"result": null, "explanation": "It is balanced."}\n```'
    )
    coach = CodexCoach(FakeAnalyzer(), runner=runner)

    answer = coach.answer_sync(START_FEN, "eval_bucket")

    assert answer.eval_bucket == "equal"


def test_codex_failure_raises_agent_error() -> None:
    coach = CodexCoach(FakeAnalyzer(), runner=FakeRunner("", returncode=1))

    with pytest.raises(CoachAgentError):
        coach.answer_sync(START_FEN, "best_move")


async def test_codex_chat_session_yields_explanation() -> None:
    runner = FakeRunner(
        '```json\n{"best_move": null, "eval_bucket": "equal", '
        '"result": null, "explanation": "Both sides can develop normally."}\n```'
    )
    session = CodexChatSession(FakeAnalyzer(), runner=runner)

    async with session:
        chunks = [chunk async for chunk in session.stream(START_FEN, "What now?")]

    assert chunks == ["Both sides can develop normally."]

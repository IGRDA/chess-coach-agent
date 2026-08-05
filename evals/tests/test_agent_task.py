"""Unit tests for routing eval inputs into the real-agent adapter."""

from __future__ import annotations

import pytest

from evals.harness.agent_task import answer_for_input, cache_key
from evals.harness.task import CoachInput


class FakeCoach:
    """Captures which AgentCoach method the harness selected."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def general_chat_sync(self, message: str, level: str | None = None) -> str:
        self.calls.append(("general_chat", message, level))
        return "general reply"

    def converse_sync(
        self,
        fen: str | None,
        history: list[tuple[str, str]],
        message: str,
        level: str | None = None,
    ) -> str:
        self.calls.append(("converse", (fen, history, message, level)))
        return "conversation reply"

    def teach_sync(self, fen: str, message: str, level: str | None = None) -> str:
        self.calls.append(("teach", message, level))
        return "teaching reply"

    def answer_sync(
        self,
        fen: str,
        task_type: str,
        level: str | None = None,
        question: str | None = None,
        candidate_move: str | None = None,
    ) -> object:
        self.calls.append((task_type, question, level))
        raise AssertionError("structured path should not run in this test")


def test_general_chat_routes_to_general_chat_method() -> None:
    coach = FakeCoach()
    result = answer_for_input(
        coach,  # type: ignore[arg-type]
        CoachInput(
            fen=None,
            task_type="general_chat",
            level="advanced",
            context="How should I reduce blunders?",
        ),
    )

    assert result.explanation == "general reply"
    assert coach.calls == [
        ("general_chat", "How should I reduce blunders?", "advanced")
    ]


def test_conversation_routes_to_converse_method() -> None:
    coach = FakeCoach()
    history = [("student", "I wanted to push a pawn.")]
    result = answer_for_input(
        coach,  # type: ignore[arg-type]
        CoachInput(
            fen=None,
            task_type="conversation",
            level="advanced",
            context="What should I do now?",
            conversation_history=history,
        ),
    )

    assert result.explanation == "conversation reply"
    assert coach.calls == [
        ("converse", (None, history, "What should I do now?", "advanced"))
    ]


def test_structured_task_without_fen_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires a FEN"):
        answer_for_input(
            FakeCoach(),  # type: ignore[arg-type]
            CoachInput(fen=None, task_type="best_move", level="beginner"),
        )


def test_cache_key_includes_general_chat_question() -> None:
    first = cache_key("fp", "general_chat", "advanced", None, "How to train?")
    second = cache_key("fp", "general_chat", "advanced", None, "What to study?")

    assert first != second


def test_conversation_cache_key_includes_history() -> None:
    first = cache_key(
        "fp",
        "conversation",
        "advanced",
        None,
        "What now?",
        history=[("student", "I pushed the pawn.")],
    )
    second = cache_key(
        "fp",
        "conversation",
        "advanced",
        None,
        "What now?",
        history=[("student", "I improved the knight.")],
    )

    assert first != second

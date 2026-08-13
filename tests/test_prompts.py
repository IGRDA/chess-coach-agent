"""Production prompt assets have one canonical, provider-aware home."""

from __future__ import annotations

from chess_coach.adapters.coach import agent, chat, codex_agent, open_chat, prompts
from chess_coach.adapters.coach.analysis import PositionAnalysis


def test_claude_adapter_keeps_legacy_prompt_exports_from_catalog() -> None:
    assert agent._SYSTEM_PROMPT is prompts.CLAUDE_SYSTEM_PROMPT
    assert agent._TASK_BRIEF is prompts.CLAUDE_TASK_BRIEFS
    assert agent._TEACH_SYSTEM_PROMPT is prompts.CLAUDE_TEACH_SYSTEM_PROMPT
    assert (
        agent._GENERAL_CHAT_SYSTEM_PROMPT is prompts.CLAUDE_GENERAL_CHAT_SYSTEM_PROMPT
    )
    assert (
        agent._CONVERSATION_SYSTEM_PROMPT is prompts.CLAUDE_CONVERSATION_SYSTEM_PROMPT
    )
    assert agent._build_prompt is prompts.build_claude_prompt
    assert agent._build_teach_prompt is prompts.build_claude_teach_prompt
    assert agent._build_general_chat_prompt is prompts.build_claude_general_chat_prompt
    assert agent._build_conversation_prompt is prompts.build_claude_conversation_prompt


def test_chat_adapters_take_their_prompts_from_catalog() -> None:
    assert chat._CHAT_SYSTEM_PROMPT is prompts.CLAUDE_CHAT_SYSTEM_PROMPT
    assert chat._build_chat_prompt is prompts.build_claude_chat_prompt
    assert open_chat._OPEN_CHAT_SYSTEM_PROMPT is prompts.OPEN_CHAT_SYSTEM_PROMPT


def test_codex_adapter_keeps_legacy_prompt_exports_from_catalog() -> None:
    assert codex_agent._SYSTEM_PROMPT is prompts.CODEX_SYSTEM_PROMPT
    assert codex_agent._TASK_BRIEF is prompts.CODEX_TASK_BRIEFS
    assert codex_agent._TEACH_SYSTEM_PROMPT is prompts.CODEX_TEACH_SYSTEM_PROMPT
    assert (
        codex_agent._GENERAL_CHAT_SYSTEM_PROMPT
        is prompts.CODEX_GENERAL_CHAT_SYSTEM_PROMPT
    )
    assert (
        codex_agent._CONVERSATION_SYSTEM_PROMPT
        is prompts.CODEX_CONVERSATION_SYSTEM_PROMPT
    )


def test_codex_answer_builder_delegates_without_changing_rendered_prompt() -> None:
    coach = object.__new__(codex_agent.CodexCoach)
    analysis = PositionAnalysis(
        best_move_uci="e2e4",
        best_move_san="e4",
        cp=20,
        mate=None,
        bucket="equal",
        result="draw",
    )
    truth: dict[str, object] = {
        "best_move_uci": "e2e4",
        "eval_bucket": "equal",
    }

    rendered = coach._build_prompt(
        "<fen>",
        "best_move",
        "beginner",
        "Why?",
        None,
        analysis,
        truth=truth,
    )

    assert rendered == prompts.build_codex_prompt(
        "<fen>", "best_move", "beginner", "Why?", truth
    )

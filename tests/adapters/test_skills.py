"""Canonical coaching skills are shared and translated at provider boundaries."""

from __future__ import annotations

from chess_coach.adapters.coach.skills import (
    SKILLS_DIR,
    capabilities_for,
    codex_skill_prompt,
    fingerprint_text,
    load_skill,
    render_skill,
    skill_for_task,
)


def test_canonical_library_is_model_neutral_and_complete() -> None:
    assert SKILLS_DIR.parts[-2:] == (".agents", "skills")
    names = {
        "assessment-coach",
        "endgame-coach",
        "general-coach",
        "interactive-coach",
        "tactics-coach",
    }
    for name in names:
        skill = load_skill(name)
        assert skill.name == name
        assert skill.description
        assert "allowed-tools" not in (SKILLS_DIR / name / "SKILL.md").read_text()


def test_claude_discovery_path_is_only_a_compatibility_link() -> None:
    compatibility = SKILLS_DIR.parents[1] / ".claude" / "skills"

    assert compatibility.is_symlink()
    assert compatibility.resolve() == SKILLS_DIR.resolve()


def test_task_selection_covers_every_evaluation_shape() -> None:
    expected = {
        "best_move": "tactics-coach",
        "deep_line": "tactics-coach",
        "eval_bucket": "assessment-coach",
        "endgame": "endgame-coach",
        "teaching": "interactive-coach",
        "mistake_diagnosis": "interactive-coach",
        "multi_turn_teaching": "interactive-coach",
        "conversation": "interactive-coach",
        "general_chat": "general-coach",
    }
    assert {task: skill_for_task(task) for task in expected} == expected


def test_provider_rendering_translates_the_same_method() -> None:
    claude = render_skill("tactics-coach", "claude")
    codex = render_skill("tactics-coach", "codex")

    assert "# Tactics coach" in claude
    assert "# Tactics coach" in codex
    assert "in-process chess tools" in claude
    assert "precomputed by the application" in codex
    assert "analyze_position" in capabilities_for("tactics-coach")


def test_codex_prompt_explicitly_activates_and_embeds_the_skill() -> None:
    prompt = codex_skill_prompt("assessment-coach", "Position FEN: test")

    assert prompt.startswith("Use $assessment-coach")
    assert "# Active skill: assessment-coach" in prompt
    assert "Position FEN: test" in prompt


def test_references_participate_in_rendering_and_cache_fingerprint() -> None:
    rendered = render_skill("interactive-coach", "claude")

    assert "Included skill reference: references/coaching-notes.md" in rendered
    assert "Spoiler control" in rendered
    assert "general-coach" in fingerprint_text()

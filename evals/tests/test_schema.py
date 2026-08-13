"""Unit tests for the golden schema invariants and the loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.data.loader import load_goldens
from evals.data.schema import ChessGolden

CANDIDATE_BANK = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "candidates"
    / "general_chat_top100.json"
)

STARTPOS = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _golden(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "x1",
        "source": "test",
        "fen": STARTPOS,
        "task": "best_move",
        "solution_moves": ["e4"],
        "extraction": {"method": "hand"},
    }
    base.update(overrides)
    return base


def test_valid_golden_parses() -> None:
    golden = ChessGolden.model_validate(_golden())
    assert golden.task == "best_move"


def test_illegal_fen_rejected() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(_golden(fen="garbage"))


def test_illegal_solution_move_rejected() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(_golden(solution_moves=["e2e5"]))


def test_best_move_requires_a_move() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(_golden(solution_moves=[]))


def test_eval_bucket_requires_bucket() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(
            _golden(task="eval_bucket", solution_moves=[], expected_bucket=None)
        )


def test_unknown_bucket_rejected() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(
            _golden(task="eval_bucket", solution_moves=[], expected_bucket="great")
        )


def test_endgame_requires_result_and_move() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(_golden(task="endgame", expected_result=None))


def test_general_chat_accepts_question_without_fen() -> None:
    golden = ChessGolden.model_validate(
        {
            "id": "gc",
            "source": "test source",
            "task": "general_chat",
            "student_message": "How should I analyze my own games?",
            "reference_explanation": "Review the game before engine use, identify "
            "turning points, then check tactics and plans.",
            "key_ideas": ["self-review first", "identify turning points"],
            "level": "intermediate",
            "extraction": {"method": "curated"},
        }
    )
    assert golden.fen is None
    assert golden.student_message


def test_general_chat_rejects_missing_ground_truth() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(
            {
                "id": "gc",
                "source": "test source",
                "task": "general_chat",
                "student_message": "How should I study?",
                "reference_explanation": "Study with a plan.",
                "key_ideas": [],
                "level": "beginner",
                "extraction": {"method": "curated"},
            }
        )


def test_position_tasks_still_require_fen() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(
            {
                "id": "bm-no-fen",
                "source": "test",
                "task": "best_move",
                "solution_moves": [],
                "extraction": {"method": "hand"},
            }
        )


def test_conversation_accepts_history_and_no_fen() -> None:
    golden = ChessGolden.model_validate(
        {
            "id": "conv",
            "source": "paraphrased book dialogue",
            "task": "conversation",
            "conversation_history": [
                {"role": "student", "text": "I want to push my f-pawn."},
                {"role": "coach", "text": "First ask what that does to your pieces."},
            ],
            "student_message": "So what should I improve instead?",
            "reference_explanation": "Improve the pieces before committing pawns.",
            "key_ideas": ["improve pieces before pawn pushes"],
            "required_facts": ["improve pieces"],
            "spoiler_policy": "none",
            "extraction": {"method": "paraphrased"},
        }
    )
    assert golden.fen is None
    assert len(golden.conversation_history) == 2


def test_conversation_requires_history_and_key_ideas() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(
            {
                "id": "conv",
                "source": "paraphrased book dialogue",
                "task": "conversation",
                "student_message": "What now?",
                "reference_explanation": "Use the prior dialogue.",
                "key_ideas": [],
                "extraction": {"method": "paraphrased"},
            }
        )


def test_load_goldens_rejects_duplicate_ids(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps([_golden(id="dup")]))
    (tmp_path / "b.json").write_text(json.dumps([_golden(id="dup")]))
    with pytest.raises(ValueError, match="duplicate"):
        load_goldens(goldens_dir=tmp_path)


def test_empty_reference_explanation_rejected() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(_golden(reference_explanation="   "))


def test_reference_explanation_and_key_ideas_accepted() -> None:
    golden = ChessGolden.model_validate(
        _golden(
            reference_explanation="The knight fork wins the queen.",
            key_ideas=["knight fork", "win material"],
        )
    )
    assert golden.reference_explanation
    assert golden.key_ideas == ["knight fork", "win material"]


def test_deep_line_requires_line_prompt_explanation_and_key_ideas() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(
            _golden(
                task="deep_line",
                solution_moves=[],
                expected_line=[],
                student_message="Calculate.",
                reference_explanation="A line.",
                key_ideas=["calculation"],
            )
        )


def test_deep_line_validates_sequence_legality() -> None:
    golden = ChessGolden.model_validate(
        _golden(
            task="deep_line",
            solution_moves=[],
            expected_line=["e4", "e5", "Nf3"],
            student_message="Calculate.",
            reference_explanation="The line develops and contests the center.",
            key_ideas=["center", "development"],
        )
    )
    assert golden.expected_line == ["e4", "e5", "Nf3"]

    with pytest.raises(ValidationError):
        ChessGolden.model_validate(
            _golden(
                task="deep_line",
                solution_moves=[],
                expected_line=["e4", "e5", "e5"],
                student_message="Calculate.",
                reference_explanation="Illegal repeat move.",
                key_ideas=["illegal"],
            )
        )


def test_committed_goldens_all_load() -> None:
    goldens = load_goldens()
    assert goldens, "expected at least the seed goldens"
    assert len({g.id for g in goldens}) == len(goldens)


def test_committed_goldens_are_color_balanced_by_task() -> None:
    goldens = load_goldens()
    balanced_tasks = {"best_move", "eval_bucket", "endgame", "teaching"}
    counts: dict[str, dict[str, int]] = {}
    for golden in goldens:
        if golden.task not in balanced_tasks or golden.fen is None:
            continue
        turn = golden.fen.split()[1]
        by_color = counts.setdefault(golden.task, {"w": 0, "b": 0})
        by_color[turn] += 1

    assert counts
    for task, by_color in counts.items():
        if task == "deep_line":
            continue
        assert by_color["w"] == by_color["b"], f"{task}: {by_color}"


def test_mistake_diagnosis_requires_student_move_and_weakness() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(
            _golden(
                task="mistake_diagnosis",
                student_message="Why was my move bad?",
                student_move="e4",
                engine_best_move="d4",
                engine_refutation="A concrete refutation.",
                reference_explanation="The move missed the tactic.",
            )
        )


def test_multi_turn_teaching_requires_conversation() -> None:
    with pytest.raises(ValidationError):
        ChessGolden.model_validate(
            _golden(
                task="multi_turn_teaching",
                solution_moves=["e4"],
                reference_explanation="A hint ladder should be present.",
            )
        )


def test_general_chat_candidate_bank_matches_selected_goldens() -> None:
    candidates = json.loads(CANDIDATE_BANK.read_text())
    assert isinstance(candidates, list)
    assert len(candidates) == 100
    assert [c["rank"] for c in candidates] == list(range(1, 101))

    selected = {c["id"] for c in candidates if c["selected"]}
    general_goldens = {g.id for g in load_goldens("general_chat")}
    assert len(selected) == 20
    assert selected == general_goldens


def test_general_chat_goldens_have_planned_level_mix() -> None:
    counts = {"beginner": 0, "intermediate": 0, "advanced": 0}
    for golden in load_goldens("general_chat"):
        counts[golden.level] += 1

    assert counts == {"beginner": 4, "intermediate": 8, "advanced": 8}


def test_deep_line_committed_goldens_have_expected_distribution() -> None:
    goldens = load_goldens("deep_line")
    assert len(goldens) == 20
    levels = {
        level: sum(1 for g in goldens if g.level == level) for level in _levels(goldens)
    }
    assert levels == {"advanced": 12, "expert": 4, "intermediate": 4}
    assert all(3 <= len(g.expected_line) <= 5 for g in goldens)


def _levels(goldens: list[ChessGolden]) -> set[str]:
    return {golden.level for golden in goldens}


def test_committed_conversations_have_expected_count_and_context_mix() -> None:
    conversations = load_goldens("conversation")
    assert len(conversations) == 50
    lengths = [len(g.conversation_history) for g in conversations]
    assert sum(2 <= n <= 3 for n in lengths) == 15
    assert sum(4 <= n <= 6 for n in lengths) == 25
    assert sum(7 <= n <= 8 for n in lengths) == 10

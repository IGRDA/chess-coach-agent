"""The goldens map to well-formed Phoenix examples (pure, no server)."""

from __future__ import annotations

from evals.data.schema import ChessGolden
from evals.phoenix.dataset import DATASETS, examples_for_task

EXPECTED_COUNTS = {
    "chess-best-move": 20,
    "chess-eval-bucket": 20,
    "chess-endgame": 20,
    "chess-teaching": 12,
    "chess-deep-line": 20,
    "chess-mistake-diagnosis": 10,
    "chess-multi-turn-teaching": 10,
    "chess-conversation": 50,
    "chess-general-chat": 20,
}


def test_dataset_counts_match_the_documented_split() -> None:
    for name, task in DATASETS.items():
        assert len(examples_for_task(task)) == EXPECTED_COUNTS[name], name


def test_example_shape_and_golden_roundtrip() -> None:
    example = examples_for_task("best_move")[0]
    assert set(example) == {"input", "output", "metadata"}
    assert set(example["input"]) >= {"fen", "task", "level", "student_message"}
    assert set(example["output"]) >= {
        "solution_moves",
        "expected_bucket",
        "expected_result",
        "reference_explanation",
        "key_ideas",
    }
    # The full golden rides in metadata so evaluators can rebuild it exactly.
    golden = ChessGolden.model_validate(example["metadata"]["golden"])
    assert golden.id == example["metadata"]["id"]
    assert golden.task == "best_move"


def test_every_task_example_carries_its_task() -> None:
    for task in DATASETS.values():
        for example in examples_for_task(task):
            assert example["input"]["task"] == task

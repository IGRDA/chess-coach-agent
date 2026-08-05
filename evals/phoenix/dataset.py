"""Map the committed goldens to Phoenix dataset examples — pure, no network.

The goldens in ``evals/data/goldens/*.json`` stay the single source of truth; this
module just reshapes them into the ``{input, output, metadata}`` example shape Phoenix
datasets take, one dataset per task. The whole serialized golden rides in ``metadata``
so an evaluator can rebuild the typed :class:`ChessGolden` exactly and reuse the same
grading the deepeval suite runs.

Kept import-only (no client, no I/O beyond loading goldens) so the mapping is unit
tested without a running Phoenix.
"""

from __future__ import annotations

from typing import Any

from evals.data.loader import load_goldens
from evals.data.schema import ChessGolden
from evals.harness.task import TaskType

# The nine per-task datasets (name → task). Names are stable so re-uploads version the
# same dataset rather than spawning new ones.
DATASETS: dict[str, TaskType] = {
    "chess-best-move": "best_move",
    "chess-eval-bucket": "eval_bucket",
    "chess-endgame": "endgame",
    "chess-teaching": "teaching",
    "chess-deep-line": "deep_line",
    "chess-mistake-diagnosis": "mistake_diagnosis",
    "chess-multi-turn-teaching": "multi_turn_teaching",
    "chess-conversation": "conversation",
    "chess-general-chat": "general_chat",
}


def _example(golden: ChessGolden) -> dict[str, Any]:
    """One golden as a Phoenix example: human-facing input/output + full golden."""
    return {
        "input": {
            "fen": golden.fen,
            "task": golden.task,
            "level": golden.level,
            "student_message": golden.student_message,
        },
        "output": {
            "solution_moves": golden.solution_moves,
            "expected_bucket": golden.expected_bucket,
            "expected_result": golden.expected_result,
            "reference_explanation": golden.reference_explanation,
            "key_ideas": golden.key_ideas,
        },
        "metadata": {
            "id": golden.id,
            "source": golden.source,
            "theme": golden.theme,
            "extraction": golden.extraction.model_dump(),
            # The exact record, so evaluators rebuild ChessGolden and reuse the metrics.
            "golden": golden.model_dump(mode="json"),
        },
    }


def examples_for_task(task: TaskType) -> list[dict[str, Any]]:
    """All goldens for one task, as Phoenix example dicts (sorted by id)."""
    return [_example(g) for g in load_goldens(task)]

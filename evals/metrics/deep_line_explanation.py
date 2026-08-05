"""The opt-in LLM-as-judge for deep-line coaching explanations.

The deterministic deep-line metric grades the move sequence. This judge covers
the coaching part: whether the answer explains why the line works, respects the
book-derived key ideas, and does not treat a multi-move problem as a one-move
trick.
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.models import AnthropicModel, DeepEvalBaseLLM
from deepeval.test_case import SingleTurnParams

JUDGE_MODEL = "claude-opus-4-8"

_CRITERIA = (
    "You are grading a chess coach's explanation of a multi-move line. "
    "'Expected output' contains the correct continuation, the book-derived key "
    "ideas, and the reference explanation. Judge the actual output on: "
    "(1) line understanding — it explains the first move and the opponent's best "
    "reply or defensive resource, not only the first move; (2) correctness — its "
    "concrete chess claims do not contradict the expected line or key ideas; "
    "(3) strategic depth — it names the plan, forcing idea, conversion method, "
    "or prophylactic reason that makes the line work; (4) coaching usefulness — "
    "it is pitched to the stated level and helps a student calculate similar "
    "positions. Penalize shallow one-move answers and invented variations."
)


def deep_line_explanation_metric(
    *, model: DeepEvalBaseLLM | None = None, threshold: float = 0.7
) -> GEval:
    """Build the deep-line explanation judge (defaults to Claude Opus 4.8)."""
    judge = model or AnthropicModel(model=JUDGE_MODEL)
    return GEval(
        name="DeepLineExplanationQuality",
        criteria=_CRITERIA,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=threshold,
    )

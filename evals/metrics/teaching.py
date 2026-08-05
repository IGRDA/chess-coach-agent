"""The opt-in LLM-as-judge for a *teaching* turn: does the coach teach well?

Where the explanation judge grades a one-shot answer's prose, this one grades a reply
in a live lesson — and adds the concern a coach can most easily get wrong: **spoiler
control**. When the student asked for a hint, revealing the best move is a failure even
if the move is correct. It is a deepeval ``GEval`` metric driven by Claude, imported
only by the ``judge``-marked tests, so the default suite stays network-free. Needs
``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.models import AnthropicModel, DeepEvalBaseLLM
from deepeval.test_case import SingleTurnParams

JUDGE_MODEL = "claude-opus-4-8"

_CRITERIA = (
    "You are grading a chess coach's reply during a live lesson. 'Input' is what the "
    "student said. 'Expected output' states the correct answer, the key ideas, whether "
    "the coach should withhold or reveal the move, and — when present — the chess "
    "book's explanation. Judge the coach's reply ('actual output') on: "
    "(1) correctness — any concrete claim it makes (the best move, the assessment) "
    "agrees with the correct answer, and it never asserts a wrong move as best; "
    "(2) spoiler control — when the expected output says to withhold the move, the "
    "reply must guide with a hint or a question and must NOT state the best move; when "
    "it says to reveal, the reply must state the answer plainly; (3) teaching "
    "quality — it engages the student, points toward the right idea, and is pitched "
    "to them; (4) relevance — it responds to what the student actually asked. Reward "
    "a helpful, honest coach; penalize spoiling a requested hint or giving a wrong or "
    "unfounded answer. Ignore verbosity and style."
)


def teaching_quality_metric(
    *, model: DeepEvalBaseLLM | None = None, threshold: float = 0.7
) -> GEval:
    """Build the teaching-quality judge (defaults to Claude Opus 4.8)."""
    judge = model or AnthropicModel(model=JUDGE_MODEL)
    return GEval(
        name="TeachingQuality",
        criteria=_CRITERIA,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=threshold,
    )

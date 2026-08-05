"""The opt-in LLM-as-judge: is the coach's *explanation* sound?

Structured correctness is graded exactly elsewhere; this judge covers only what
exact match cannot — whether the prose names the right move/idea and never
contradicts the engine's verdict. It is a deepeval ``GEval`` metric driven by
Claude, imported only by the ``judge``-marked tests, so the default suite stays
network-free. Needs ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.models import AnthropicModel, DeepEvalBaseLLM
from deepeval.test_case import SingleTurnParams

JUDGE_MODEL = "claude-opus-4-8"

_CRITERIA = (
    "You are grading a chess coach's written explanation of a position. "
    "'Expected output' is the ground truth: the correct answer (best/key move, "
    "assessment, or result), the key ideas, and — when present — the chess book's "
    "own explanation of the position. Judge the explanation ('actual output') on: "
    "(1) correctness — it identifies the right move/assessment and its reasoning "
    "agrees with the ground truth; (2) faithfulness — it invents no evaluation that "
    "contradicts the ground truth and does not miss the book's central point; "
    "(3) relevance — it conveys the key ideas. Reward an explanation that reaches "
    "the same understanding as the book even if worded differently; ignore verbosity "
    "and style."
)


def explanation_quality_metric(
    *, model: DeepEvalBaseLLM | None = None, threshold: float = 0.7
) -> GEval:
    """Build the explanation-quality judge (defaults to Claude Opus 4.8)."""
    judge = model or AnthropicModel(model=JUDGE_MODEL)
    return GEval(
        name="ExplanationQuality",
        criteria=_CRITERIA,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=threshold,
    )

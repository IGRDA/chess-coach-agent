"""The opt-in LLM-as-judge for general chess coaching questions.

These cases are not tied to a concrete board position. The judge grades whether
the coach gives source-grounded chess advice, includes the required key facts, and
pitches the explanation to the student's stated level. It is imported only by the
``judge``-marked tests, so the default deterministic suite stays network-free.
Needs ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.models import AnthropicModel, DeepEvalBaseLLM
from deepeval.test_case import SingleTurnParams

JUDGE_MODEL = "claude-opus-4-8"

_CRITERIA = (
    "You are grading a chess coach's answer to a general chess question, not a "
    "specific board position. 'Input' is the student's question. 'Expected output' "
    "contains the student's level, a paraphrased source-backed reference answer, "
    "and required key facts. Judge the coach's reply ('actual output') on: "
    "(1) factual correctness — it agrees with the reference answer and does not "
    "invent unsupported rules, book claims, engine claims, or statistics; "
    "(2) key-fact coverage — it includes the essential facts and distinctions; "
    "(3) coaching usefulness — it turns the facts into practical advice or a "
    "training action; (4) level fit — it explains at the requested level without "
    "being misleadingly shallow or needlessly opaque. Penalize vague generic "
    "answers, confident false claims, and answers that require a position but fail "
    "to say so. Ignore style preferences unless they hurt clarity or coaching value."
)


def general_chat_quality_metric(
    *, model: DeepEvalBaseLLM | None = None, threshold: float = 0.7
) -> GEval:
    """Build the general-chat judge (defaults to Claude Opus 4.8)."""
    judge = model or AnthropicModel(model=JUDGE_MODEL)
    return GEval(
        name="GeneralChatQuality",
        criteria=_CRITERIA,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=threshold,
    )

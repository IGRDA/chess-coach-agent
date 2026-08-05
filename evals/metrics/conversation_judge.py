"""The opt-in LLM-as-judge for multi-turn coaching conversations.

The deterministic policy metric catches cheap failures first. This judge grades
the actual teaching: whether the coach remembers the transcript, addresses the
student's current misconception, covers the book-derived key ideas, and respects
the reveal/withhold policy.
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.models import AnthropicModel, DeepEvalBaseLLM
from deepeval.test_case import SingleTurnParams

JUDGE_MODEL = "claude-opus-4-8"

_CRITERIA = (
    "You are grading a chess coach's final reply in a multi-turn lesson. 'Input' "
    "contains the current FEN if any, the prior student/coach transcript, and the "
    "student's latest message. 'Expected output' contains the spoiler policy, "
    "book-derived reference answer, required facts/key ideas, and forbidden claims. "
    "Judge the actual coach reply on: (1) factual correctness — any chess claim "
    "agrees with the expected facts and does not include forbidden claims; "
    "(2) context awareness — it uses the prior dialogue, remembers the student's "
    "goal or misconception, and does not restart as if this were a fresh question; "
    "(3) teaching quality — it guides, corrects, or reveals according to the "
    "situation and level; (4) spoiler policy — it withholds or reveals concrete "
    "answers as requested; (5) relevance — it answers the latest student turn. "
    "Penalize generic advice, hallucinated variations, and ignoring previous hints."
)


def conversation_quality_metric(
    *, model: DeepEvalBaseLLM | None = None, threshold: float = 0.7
) -> GEval:
    """Build the conversation-quality judge (defaults to Claude Opus 4.8)."""
    judge = model or AnthropicModel(model=JUDGE_MODEL)
    return GEval(
        name="ConversationQuality",
        criteria=_CRITERIA,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=threshold,
    )

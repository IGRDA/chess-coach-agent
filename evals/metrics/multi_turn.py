"""The opt-in LLM-as-judge for a multi-turn teaching transcript.

The deterministic chess checks can say what the right answer is; this judge grades
the teaching process across several exchanges. It especially checks spoiler control
before the reveal turn, adaptation to student guesses, correction of misconceptions
and a final summary of the transferable idea.
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.models import AnthropicModel, DeepEvalBaseLLM
from deepeval.test_case import SingleTurnParams

JUDGE_MODEL = "claude-opus-4-8"

_CRITERIA = (
    "You are grading a multi-turn chess coaching transcript. 'Input' lists the "
    "student turns. 'Expected output' contains the correct chess answer, the first "
    "turn on which the coach may reveal it, per-turn reveal rules, required ideas, "
    "forbidden spoilers, and the reference explanation. Judge the coach transcript "
    "('actual output') on: (1) spoiler control — before the allowed reveal turn it "
    "must guide without naming the concrete answer; (2) adaptation — it should react "
    "to the student's guesses and misconceptions rather than repeating a canned hint; "
    "(3) correctness — when it reveals or summarizes, the chess facts match the "
    "ground truth; (4) teaching progression — hint, response, correction and summary "
    "move the student toward the right idea. Penalize early spoilers, wrong concrete "
    "moves/evaluations, or transcripts that never reach the central idea."
)


def multi_turn_teaching_quality_metric(
    *, model: DeepEvalBaseLLM | None = None, threshold: float = 0.7
) -> GEval:
    """Build the multi-turn teaching judge (defaults to Claude Opus 4.8)."""
    judge = model or AnthropicModel(model=JUDGE_MODEL)
    return GEval(
        name="MultiTurnTeachingQuality",
        criteria=_CRITERIA,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=threshold,
    )

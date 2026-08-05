"""The opt-in LLM-as-judge for diagnosing a student's mistake.

This judge grades what exact-match chess checks cannot: whether the coach explains
why the student's move was wrong, anchors the correction in the engine's best move
and refutation, and turns the error into a reusable habit. It is imported only by
``judge``-marked tests, so the default suite stays network-free.
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.models import AnthropicModel, DeepEvalBaseLLM
from deepeval.test_case import SingleTurnParams

JUDGE_MODEL = "claude-opus-4-8"

_CRITERIA = (
    "You are grading a chess coach's diagnosis of a student's move. 'Input' is the "
    "student's question or move. 'Expected output' contains the student move, the "
    "engine-best move, the engine refutation, weakness tags, key ideas and reference "
    "explanation. Judge the coach's reply ('actual output') on: "
    "(1) correctness — it identifies whether the student move is bad and does not "
    "contradict the engine-best move or refutation; (2) diagnosis — it explains the "
    "specific reason the move fails, not just that it is wrong; (3) habit transfer — "
    "it names the reusable weakness or thinking habit to improve; (4) coaching fit — "
    "it is candid, useful and pitched to the student's level. Penalize generic advice, "
    "wrong concrete chess claims, or missing the main weakness."
)


def mistake_diagnosis_quality_metric(
    *, model: DeepEvalBaseLLM | None = None, threshold: float = 0.7
) -> GEval:
    """Build the mistake-diagnosis judge (defaults to Claude Opus 4.8)."""
    judge = model or AnthropicModel(model=JUDGE_MODEL)
    return GEval(
        name="MistakeDiagnosisQuality",
        criteria=_CRITERIA,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=threshold,
    )

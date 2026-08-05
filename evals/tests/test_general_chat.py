"""Opt-in LLM-as-judge: does the coach answer general chess questions well?

Each golden is a non-position student question backed by paraphrased facts from
the curated book/Stack Exchange source bank. The coach's reply is judged for
correctness, key-fact coverage, practical coaching value, and level fit.
"""

from __future__ import annotations

import os

import pytest

from evals.data.loader import coach_input, load_goldens, to_general_chat_case
from evals.data.schema import ChessGolden
from evals.harness.task import CoachResult, CoachTask
from evals.tests._support import run_or_xfail

pytestmark = pytest.mark.judge

GENERAL_CHAT = load_goldens("general_chat")


@pytest.fixture(scope="module")
def judge() -> object:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from evals.metrics.general_chat import general_chat_quality_metric

    return general_chat_quality_metric()


def test_source_faithful_general_answer_passes(judge: object) -> None:
    golden = GENERAL_CHAT[0]
    result = CoachResult(
        explanation=(
            f"For a {golden.level} player, the key is to combine: "
            f"{'; '.join(golden.key_ideas)}. {golden.reference_explanation}"
        )
    )
    judge.measure(to_general_chat_case(golden, result))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]


def test_vague_general_answer_fails(judge: object) -> None:
    golden = GENERAL_CHAT[0]
    result = CoachResult(
        explanation=(
            "Just practice a lot, stay positive, and everything will eventually "
            "improve."
        )
    )
    judge.measure(to_general_chat_case(golden, result))  # type: ignore[attr-defined]
    assert not judge.is_successful()  # type: ignore[attr-defined]


@pytest.mark.parametrize("golden", GENERAL_CHAT, ids=[g.id for g in GENERAL_CHAT])
def test_coach_answers_general_chess_question(
    golden: ChessGolden, coach_task: CoachTask, judge: object
) -> None:
    """The coach's general answer is judged against source-backed key facts."""
    result = run_or_xfail(coach_task, coach_input(golden))
    if not result.explanation.strip():
        pytest.xfail("reference coach produces no general-chat answer to judge")
    judge.measure(to_general_chat_case(golden, result))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]

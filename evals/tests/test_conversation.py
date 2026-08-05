"""Opt-in LLM-as-judge: multi-turn teacher-student conversation evals."""

from __future__ import annotations

import os

import pytest

from evals.data.loader import coach_input, load_goldens, to_conversation_case
from evals.data.schema import ChessGolden
from evals.harness.task import CoachResult, CoachTask
from evals.metrics import ConversationPolicyMetric
from evals.tests._support import run_or_xfail

pytestmark = pytest.mark.judge

CONVERSATIONS = load_goldens("conversation")


@pytest.fixture(scope="module")
def judge() -> object:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from evals.metrics.conversation_judge import conversation_quality_metric

    return conversation_quality_metric()


def test_context_aware_conversation_reply_passes(judge: object) -> None:
    golden = CONVERSATIONS[0]
    result = CoachResult(
        explanation=(
            f"You were asking about {golden.key_ideas[0]}. "
            f"{golden.reference_explanation}"
        )
    )
    judge.measure(to_conversation_case(golden, result))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]


def test_generic_conversation_reply_fails(judge: object) -> None:
    golden = CONVERSATIONS[0]
    result = CoachResult(explanation="Study tactics, stay positive, and play more.")
    judge.measure(to_conversation_case(golden, result))  # type: ignore[attr-defined]
    assert not judge.is_successful()  # type: ignore[attr-defined]


@pytest.mark.parametrize("golden", CONVERSATIONS, ids=[g.id for g in CONVERSATIONS])
def test_coach_handles_conversation(
    golden: ChessGolden, coach_task: CoachTask, judge: object
) -> None:
    result = run_or_xfail(coach_task, coach_input(golden))
    if not result.explanation.strip():
        pytest.xfail("reference coach produces no conversation reply to judge")
    policy = ConversationPolicyMetric()
    policy.measure(to_conversation_case(golden, result))
    assert policy.is_successful(), policy.reason
    judge.measure(to_conversation_case(golden, result))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]

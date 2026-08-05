"""Opt-in LLM-as-judge: does the coach explain deep lines well?"""

from __future__ import annotations

import os

import pytest

from evals.data.loader import coach_input, load_goldens, to_judge_case
from evals.data.schema import ChessGolden
from evals.harness.task import CoachResult, CoachTask
from evals.tests._support import run_or_xfail

pytestmark = pytest.mark.judge

DEEP_LINES = load_goldens("deep_line")


@pytest.fixture(scope="module")
def judge() -> object:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from evals.metrics.deep_line_explanation import deep_line_explanation_metric

    return deep_line_explanation_metric()


def test_one_move_answer_fails_deep_line_judge(judge: object) -> None:
    golden = DEEP_LINES[0]
    result = CoachResult(
        line=[golden.expected_line[0]],
        explanation=f"The best move is {golden.expected_line[0]}.",
    )
    judge.measure(to_judge_case(golden, result))  # type: ignore[attr-defined]
    assert not judge.is_successful()  # type: ignore[attr-defined]


@pytest.mark.parametrize("golden", DEEP_LINES, ids=[g.id for g in DEEP_LINES])
def test_coach_explains_deep_line(
    golden: ChessGolden, coach_task: CoachTask, judge: object
) -> None:
    result = run_or_xfail(coach_task, coach_input(golden))
    if not result.explanation.strip():
        pytest.xfail("reference coach produces no explanation to judge")
    judge.measure(to_judge_case(golden, result))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]

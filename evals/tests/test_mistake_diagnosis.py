"""Opt-in LLM-as-judge: does the coach diagnose a student's mistake well?

These goldens model the highest-value coaching task: a student played or proposed a
move, and the coach must explain what it misses, name the better move, cite the
engine-backed punishment and turn the error into a reusable thinking habit.
"""

from __future__ import annotations

import os

import pytest

from evals.data.loader import coach_input, load_goldens, to_mistake_case
from evals.data.schema import ChessGolden
from evals.harness.task import CoachResult, CoachTask
from evals.tests._support import run_or_xfail

pytestmark = pytest.mark.judge

MISTAKES = load_goldens("mistake_diagnosis")


@pytest.fixture(scope="module")
def judge() -> object:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from evals.metrics.mistake import mistake_diagnosis_quality_metric

    return mistake_diagnosis_quality_metric()


def test_generic_advice_fails(judge: object) -> None:
    golden = MISTAKES[0]
    result = CoachResult(
        explanation=(
            "You should calculate more carefully and try to improve your pieces "
            "before committing to a plan."
        )
    )
    judge.measure(to_mistake_case(golden, result))  # type: ignore[attr-defined]
    assert not judge.is_successful()  # type: ignore[attr-defined]


@pytest.mark.parametrize("golden", MISTAKES, ids=[g.id for g in MISTAKES])
def test_coach_diagnoses_student_mistake(
    golden: ChessGolden, coach_task: CoachTask, judge: object
) -> None:
    result = run_or_xfail(coach_task, coach_input(golden))
    if not result.explanation.strip():
        pytest.xfail("reference coach produces no diagnosis to judge")
    judge.measure(to_mistake_case(golden, result))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]

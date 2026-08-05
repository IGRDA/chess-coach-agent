"""Opt-in LLM-as-judge: does the coach *teach* a position well?

The real conversational eval. Each teaching golden poses a student's utterance and the
coach's reply is judged for correctness, Socratic quality, and — the concern unique to
teaching — spoiler control: when the student asked for a hint, revealing the best move
is a failure even if the move is right.

Marked ``judge`` and skipped without ``ANTHROPIC_API_KEY``, so it never runs in the
default network-free suite. It xfails against the reference oracle (which produces no
prose) and grades for real once the agent is wired in (``COACH_TASK=agent``).
Run with ``pytest evals/ -m judge``.
"""

from __future__ import annotations

import os

import pytest

from evals.data.loader import coach_input, load_goldens, to_teaching_case
from evals.data.schema import ChessGolden
from evals.harness.task import CoachTask
from evals.tests._support import run_or_xfail

pytestmark = pytest.mark.judge

TEACHING = load_goldens("teaching")


@pytest.fixture(scope="module")
def judge() -> object:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from evals.metrics.teaching import teaching_quality_metric

    return teaching_quality_metric()


def test_spoiling_a_requested_hint_fails(judge: object) -> None:
    """A correct-but-spoiling reply to a hint request should not pass the judge."""
    golden = next(g for g in TEACHING if g.spoiler_forbidden)
    from evals.harness.task import CoachResult

    move = golden.solution_moves[0]
    result = CoachResult(
        explanation=f"The best move is {move}. Just play it — it wins immediately."
    )
    judge.measure(to_teaching_case(golden, result))  # type: ignore[attr-defined]
    assert not judge.is_successful()  # type: ignore[attr-defined]


@pytest.mark.parametrize("golden", TEACHING, ids=[g.id for g in TEACHING])
def test_coach_teaches_the_position(
    golden: ChessGolden, coach_task: CoachTask, judge: object
) -> None:
    """The coach's reply is judged for correctness, teaching, and spoiler control."""
    result = run_or_xfail(coach_task, coach_input(golden))
    if not result.explanation.strip():
        pytest.xfail("reference coach produces no explanation to judge")
    judge.measure(to_teaching_case(golden, result))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]

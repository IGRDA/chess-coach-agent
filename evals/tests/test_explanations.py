"""Opt-in LLM-as-judge: sanity-check the explanation-quality metric.

Marked ``judge`` and skipped without ``ANTHROPIC_API_KEY``, so it never runs in
the default network-free suite. It confirms the judge wiring end-to-end: a
faithful explanation of a known position should pass, an off-topic one should not.
Run with ``pytest evals/ -m judge``.
"""

from __future__ import annotations

import os

import pytest

from evals.data.loader import (
    coach_input,
    load_explained_goldens,
    load_goldens,
    to_judge_case,
)
from evals.data.schema import ChessGolden
from evals.harness.task import CoachResult, CoachTask
from evals.tests._support import run_or_xfail

pytestmark = pytest.mark.judge

ONE_SHOT_EXPLANATION_TASKS = {"best_move", "eval_bucket", "endgame"}
EXPLAINED = [
    g for g in load_explained_goldens() if g.task in ONE_SHOT_EXPLANATION_TASKS
]


@pytest.fixture(scope="module")
def judge() -> object:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from evals.metrics.explanation import explanation_quality_metric

    return explanation_quality_metric()


def test_faithful_explanation_passes(judge: object) -> None:
    golden = load_goldens("best_move")[0]
    move = golden.solution_moves[0]
    idea = ", ".join(golden.theme) or "tactics"
    result = CoachResult(
        best_move=move,
        explanation=(
            f"The strongest move is {move}. It is best because it directly "
            f"exploits the position's key idea ({idea}), "
            "winning by force; no other move is as strong."
        ),
    )
    judge.measure(to_judge_case(golden, result))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]


def test_offtopic_explanation_fails(judge: object) -> None:
    golden = load_goldens("best_move")[0]
    result = CoachResult(
        best_move=golden.solution_moves[0],
        explanation="I enjoy long walks and the weather has been pleasant lately.",
    )
    judge.measure(to_judge_case(golden, result))  # type: ignore[attr-defined]
    assert not judge.is_successful()  # type: ignore[attr-defined]


@pytest.mark.parametrize("golden", EXPLAINED, ids=[g.id for g in EXPLAINED])
def test_coach_explanation_matches_book(
    golden: ChessGolden, coach_task: CoachTask, judge: object
) -> None:
    """The coach's prose is judged against the book's own explanation.

    This is the real explanation eval: it needs a coach that actually narrates,
    so it xfails against the reference oracle (which returns no prose) and grades
    for real once the agent is wired in.
    """
    result = run_or_xfail(coach_task, coach_input(golden))
    if not result.explanation.strip():
        pytest.xfail("reference coach produces no explanation to judge")
    judge.measure(to_judge_case(golden, result))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]

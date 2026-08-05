"""Opt-in LLM-as-judge: does a multi-turn transcript teach the position well?

The current app has a one-turn teaching adapter; these goldens define the next eval
target for comparing stronger coaches: hint without spoiling, respond to the
student's guess, reveal at the right time and summarize the transferable idea.
"""

from __future__ import annotations

import os

import pytest

from evals.data.loader import load_goldens, to_multi_turn_case

pytestmark = pytest.mark.judge

SCENARIOS = load_goldens("multi_turn_teaching")


@pytest.fixture(scope="module")
def judge() -> object:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from evals.metrics.multi_turn import multi_turn_teaching_quality_metric

    return multi_turn_teaching_quality_metric()


def test_spoiling_before_reveal_fails(judge: object) -> None:
    golden = next(g for g in SCENARIOS if (g.expected_reveal_turn or 1) > 1)
    move = golden.solution_moves[0]
    transcript = (
        f"Coach turn 1: The answer is {move}; play it immediately.\n"
        "Coach turn 2: You should have seen it sooner."
    )
    judge.measure(to_multi_turn_case(golden, transcript))  # type: ignore[attr-defined]
    assert not judge.is_successful()  # type: ignore[attr-defined]


def test_faithful_transcript_passes(judge: object) -> None:
    golden = SCENARIOS[0]
    transcript = (
        "Coach turn 1: Start by listing forcing checks and notice the king has no "
        "escape squares behind its own pawns; I will not name the move yet.\n"
        "Coach turn 2: Yes, this is a back-rank pattern. Find the rook check on the "
        "eighth rank.\n"
        "Coach turn 3: The move is Re8#, because the rook checks along the back rank "
        "and the f7, g7 and h7 pawns trap the king."
    )
    judge.measure(to_multi_turn_case(golden, transcript))  # type: ignore[attr-defined]
    assert judge.is_successful(), judge.reason  # type: ignore[attr-defined]

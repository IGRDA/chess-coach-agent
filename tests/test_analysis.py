"""Pure score→bucket and score→result mapping (no engine needed)."""

from __future__ import annotations

import pytest

from chess_coach.adapters.coach.analysis import (
    PositionAnalysis,
    bucket_from_score,
    result_from_score,
)


@pytest.mark.parametrize(
    ("cp", "mate", "bucket"),
    [
        (0, None, "equal"),
        (99, None, "equal"),
        (100, None, "better"),
        (299, None, "better"),
        (300, None, "winning"),
        (-100, None, "worse"),
        (-300, None, "losing"),
        (None, 3, "winning"),
        (None, -2, "losing"),
    ],
)
def test_bucket_from_score(cp: int | None, mate: int | None, bucket: str) -> None:
    assert bucket_from_score(cp, mate) == bucket


def test_bucket_is_symmetric_about_zero() -> None:
    for cp in (50, 150, 400):
        assert bucket_from_score(cp, None) != "losing"
        # mirror score lands in the mirror bucket
        pairs = {"better": "worse", "winning": "losing", "equal": "equal"}
        assert bucket_from_score(-cp, None) == pairs[bucket_from_score(cp, None)]


def test_bucket_requires_a_score() -> None:
    with pytest.raises(ValueError):
        bucket_from_score(None, None)


@pytest.mark.parametrize(
    ("cp", "mate", "result"),
    [
        (0, None, "draw"),
        (299, None, "draw"),
        (300, None, "win"),
        (-300, None, "loss"),
        (None, 1, "win"),
        (None, -5, "loss"),
    ],
)
def test_result_from_score(cp: int | None, mate: int | None, result: str) -> None:
    assert result_from_score(cp, mate) == result


def test_score_text_reads_mate_and_centipawns() -> None:
    mate = PositionAnalysis("a1a2", "Ka2", None, 3, "winning", "win")
    assert mate.score_text() == "#3"
    cp = PositionAnalysis("a1a2", "Ka2", 135, None, "better", "draw")
    assert cp.score_text() == "+1.35"

"""Unit tests for the pure position checkers and the bucket scale."""

from __future__ import annotations

import pytest

from evals.harness.checkers import (
    bucket_distance,
    bucket_from_score,
    is_legal_move,
    is_valid_fen,
    normalize_move,
)

STARTPOS = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_is_valid_fen_accepts_legal_and_rejects_garbage() -> None:
    assert is_valid_fen(STARTPOS)
    assert not is_valid_fen("not a fen")
    assert not is_valid_fen("8/8/8/8/8/8/8/8 w - - 0 1")  # no kings


def test_normalize_move_accepts_san_and_uci() -> None:
    assert normalize_move(STARTPOS, "e4") == "e2e4"
    assert normalize_move(STARTPOS, "e2e4") == "e2e4"
    assert normalize_move(STARTPOS, "Ng1f3") == "g1f3"


def test_normalize_move_rejects_illegal() -> None:
    assert not is_legal_move(STARTPOS, "e2e5")  # illegal push
    assert not is_legal_move(STARTPOS, "Zz9")  # unparseable
    with pytest.raises(ValueError):
        normalize_move(STARTPOS, "e2e5")


@pytest.mark.parametrize(
    ("cp", "expected"),
    [
        (500, "winning"),
        (300, "winning"),
        (299, "better"),
        (100, "better"),
        (99, "equal"),
        (0, "equal"),
        (-99, "equal"),
        (-100, "worse"),
        (-299, "worse"),
        (-300, "losing"),
    ],
)
def test_bucket_from_cp_boundaries(cp: int, expected: str) -> None:
    assert bucket_from_score(cp, None) == expected


def test_bucket_from_mate_dominates() -> None:
    assert bucket_from_score(None, 3) == "winning"
    assert bucket_from_score(None, -1) == "losing"


def test_bucket_from_score_requires_a_reading() -> None:
    with pytest.raises(ValueError):
        bucket_from_score(None, None)


def test_bucket_distance() -> None:
    assert bucket_distance("equal", "equal") == 0
    assert bucket_distance("winning", "better") == 1
    assert bucket_distance("winning", "losing") == 4
    with pytest.raises(ValueError):
        bucket_distance("equal", "nonsense")

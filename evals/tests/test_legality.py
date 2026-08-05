"""Tests for the deterministic move-legality check over coach outputs."""

from __future__ import annotations

from evals.harness.legality import (
    check_result,
    extract_move_tokens,
    illegal_in_line,
    illegal_in_prose,
)

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_extract_includes_disambiguated_moves_and_promotions() -> None:
    tokens = extract_move_tokens("Try Nf3, Bb5+, O-O, exd5, e8=Q, and e2e4.")
    assert tokens == ["Nf3", "Bb5+", "O-O", "exd5", "e8=Q", "e2e4"]


def test_extract_skips_bare_pawn_and_square_references() -> None:
    # Bare pawn destinations are ambiguous with square talk ("the e4 pawn") and skipped.
    assert extract_move_tokens("The e4 pawn controls d5 and f5.") == []


def test_legal_structured_move_and_line_pass() -> None:
    result = check_result(START, best_move="e2e4", line=["e2e4", "e7e5", "g1f3"])
    assert result.legal
    assert result.illegal == ()


def test_illegal_structured_best_move_is_flagged() -> None:
    result = check_result(START, best_move="g1e4")  # knight can't reach e4 from g1
    assert not result.legal
    assert "g1e4" in result.illegal


def test_illegal_move_in_line_is_flagged() -> None:
    bad = illegal_in_line(START, ["e2e4", "e7e5", "e2e4"])  # e2e4 twice is impossible
    assert bad == ["e2e4"]


def test_prose_hallucinated_move_is_flagged() -> None:
    result = check_result(START, explanation="Just play Qh5 immediately to attack.")
    assert not result.legal
    assert "Qh5" in result.illegal


def test_prose_one_sided_plan_is_not_flagged() -> None:
    # A coach may narrate one side's plan without the opponent's replies; the moves are
    # legal in reachable positions even though they are "out of turn".
    assert illegal_in_prose(START, "Play Nf3, then Ng5 to hit f7.") == []


def test_prose_move_deep_in_provided_line_is_not_flagged() -> None:
    # A move the coach discusses deep in the engine's own line (here dxe5 after d4)
    # must pass — the line anchors reachability so it is not a false positive.
    result = check_result(
        "4k2r/8/3p4/4n3/8/2N5/3P1P2/4R1K1 w - - 0 1",
        line=["d2d4", "e8f7", "d4e5", "d6e5"],
        explanation="After d4 you can answer the knight with dxe5.",
    )
    assert result.legal


def test_prose_hallucination_flagged_even_with_a_line() -> None:
    # A move reachable in neither the position nor the provided line is still caught.
    result = check_result(
        START,
        line=["e2e4", "e7e5"],
        explanation="Immediately play Qa6 to attack.",
    )
    assert not result.legal
    assert "Qa6" in result.illegal


def test_no_board_means_nothing_to_check() -> None:
    # General chat has no position; legality is undefined and passes vacuously.
    result = check_result(None, explanation="Play Nf3 in the opening.")
    assert result.legal
    assert result.checked == 0

"""The deterministic coaching tools: quick-sight, move scoring, candidate ranking.

Engine-free: :func:`position_features` needs nothing, and the engine-backed helpers
are exercised through a fake ``PositionAnalyzer`` whose canned evaluations make the
arithmetic (centipawn loss, verdict) predictable.
"""

from __future__ import annotations

import chess
import pytest

from chess_coach.adapters.coach.analysis import (
    PositionAnalysis,
    bucket_from_score,
    result_from_score,
)
from chess_coach.adapters.coach.tablebase import Tablebase
from chess_coach.adapters.coach.tools import (
    compare_candidates,
    evaluate_move,
    position_features,
)

# A back-rank mate in one: 1.Re8#.
MATE_FEN = "6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1"
# Black to move; White's knight on e1 is loose (attacked by the bishop, undefended).
LOOSE_FEN = "6k1/8/8/8/8/2b5/8/4N1K1 b - - 0 1"


def _analysis(
    board: chess.Board, best_uci: str, cp: int | None, mate: int | None
) -> PositionAnalysis:
    move = chess.Move.from_uci(best_uci)
    return PositionAnalysis(
        best_move_uci=best_uci,
        best_move_san=board.san(move),
        cp=cp,
        mate=mate,
        bucket=bucket_from_score(cp, mate),
        result=result_from_score(cp, mate),
    )


class FakeAnalyzer:
    """Returns a canned analysis per FEN; complains about positions it wasn't given."""

    def __init__(self, table: dict[str, PositionAnalysis]) -> None:
        self._table = table

    def analyze(self, fen: str) -> PositionAnalysis:
        if fen not in self._table:
            raise AssertionError(f"unexpected analyze() for {fen!r}")
        return self._table[fen]


# -- position_features (engine-free) ------------------------------------------------


def test_features_report_the_only_check_and_no_captures() -> None:
    features = position_features(MATE_FEN)
    assert features.side_to_move == "white"
    assert features.checks == ["Re8#"]
    assert features.captures == []
    assert features.material == {"white": 8, "black": 3}


def test_features_spot_a_loose_enemy_piece_as_a_target() -> None:
    features = position_features(LOOSE_FEN)
    # Black to move: White's undefended knight on e1 is a target Black can win.
    assert "Ne1" in features.hanging_targets
    assert features.hanging_own == []


def test_features_reject_an_illegal_position() -> None:
    with pytest.raises(ValueError):
        position_features("8/8/8/8/8/8/8/8 w - - 0 1")  # no kings


# -- evaluate_move ------------------------------------------------------------------


def test_the_best_move_scores_zero_loss_without_probing_the_child() -> None:
    board = chess.Board(MATE_FEN)
    analyzer = FakeAnalyzer({MATE_FEN: _analysis(board, "e1e8", None, 1)})
    result = evaluate_move(analyzer, MATE_FEN, "e1e8")
    assert result.is_best and result.verdict == "best"
    assert result.cp_loss == 0 and result.score_text == "#1"


def test_delivering_mate_is_recognised_even_if_not_flagged_best() -> None:
    board = chess.Board(MATE_FEN)
    # Pretend the engine prefers a different move so the mating move takes the
    # terminal branch (board.is_checkmate()) instead of the is_best short-circuit.
    analyzer = FakeAnalyzer({MATE_FEN: _analysis(board, "g1h1", None, 1)})
    result = evaluate_move(analyzer, MATE_FEN, "e1e8")
    assert result.score_text == "#"  # checkmate on the board now
    assert result.cp_loss == 0  # best was mate, this move mates → no loss


def test_a_quiet_move_that_gives_up_ground_is_scored_and_graded() -> None:
    fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    board = chess.Board(fen)
    after = board.copy()
    after.push_uci("e1d1")  # a passive king move, non-terminal
    analyzer = FakeAnalyzer(
        {
            fen: _analysis(board, "e2e4", 120, None),  # engine likes 1.e4 at +1.20
            after.fen(): _analysis(after, "e8d8", 30, None),  # opp POV +0.30 → us -0.30
        }
    )
    result = evaluate_move(analyzer, fen, "e1d1")
    assert not result.is_best
    assert result.cp_loss == 150  # 120 − (−30)
    assert result.verdict == "mistake"  # 100 ≤ 150 < 300
    assert result.score_text == "-0.30"


def test_missing_a_forced_mate_caps_the_reported_loss() -> None:
    fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    board = chess.Board(fen)
    after = board.copy()
    after.push_uci("e1d1")
    analyzer = FakeAnalyzer(
        {
            fen: _analysis(board, "e2e4", None, 2),  # engine sees mate in 2
            after.fen(): _analysis(after, "e8d8", 50, None),  # still fine for us
        }
    )
    result = evaluate_move(analyzer, fen, "e1d1")
    assert result.cp_loss == 2000  # mate-scale collapse, capped
    assert result.verdict == "blunder"


def test_evaluate_move_rejects_an_illegal_move() -> None:
    board = chess.Board(MATE_FEN)
    analyzer = FakeAnalyzer({MATE_FEN: _analysis(board, "e1e8", None, 1)})
    with pytest.raises(ValueError):
        evaluate_move(analyzer, MATE_FEN, "e1a8")  # rook can't reach a8


# -- compare_candidates -------------------------------------------------------------


def test_candidates_are_ranked_best_first() -> None:
    fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    board = chess.Board(fen)
    passive = board.copy()
    passive.push_uci("e1d1")
    analyzer = FakeAnalyzer(
        {
            fen: _analysis(board, "e2e4", 120, None),
            passive.fen(): _analysis(passive, "e8d8", 30, None),
        }
    )
    ranked = compare_candidates(analyzer, fen, ["e1d1", "e2e4"])
    assert [r.move_uci for r in ranked] == ["e2e4", "e1d1"]  # best first
    assert ranked[0].verdict == "best"


def test_compare_candidates_needs_at_least_one_move() -> None:
    with pytest.raises(ValueError):
        compare_candidates(FakeAnalyzer({}), MATE_FEN, [])


# -- tablebase (graceful when unconfigured) -----------------------------------------


def test_tablebase_is_unavailable_without_a_directory() -> None:
    tb = Tablebase(path=None)
    assert not tb.configured
    result = tb.probe("8/8/8/8/8/5k2/6p1/6K1 w - - 0 1")
    assert result.available is False and result.wdl is None


def test_tablebase_probe_still_validates_the_position() -> None:
    with pytest.raises(ValueError):
        Tablebase(path=None).probe("8/8/8/8/8/8/8/8 w - - 0 1")

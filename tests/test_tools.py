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
    board: chess.Board,
    best_uci: str,
    cp: int | None,
    mate: int | None,
    pv_san: tuple[str, ...] = (),
) -> PositionAnalysis:
    move = chess.Move.from_uci(best_uci)
    return PositionAnalysis(
        best_move_uci=best_uci,
        best_move_san=board.san(move),
        cp=cp,
        mate=mate,
        bucket=bucket_from_score(cp, mate),
        result=result_from_score(cp, mate),
        pv_san=pv_san,
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


def test_the_best_move_scores_zero_loss() -> None:
    """A mating best move is terminal, so no child search happens at all here.

    (For a non-terminal best move the child *is* probed — for its line, not its
    score; see ``test_the_best_moves_score_still_comes_from_the_parent_search``.)
    """
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


# -- evaluate_move: input forms, verdict scale, terminal branches --------------------

# A quiet king-and-pawn position used to drive the arithmetic: the engine "prefers"
# 1.e4, and 1.Kd1 is the move under review (legal, non-terminal, never the best).
QUIET_FEN = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"


def _quiet_analyzer(best_cp: int, after_cp: int) -> FakeAnalyzer:
    """Fake the two analyses ``evaluate_move`` makes, so cp_loss is exactly
    ``best_cp + after_cp`` (the child is scored from the opponent's point of view)."""
    board = chess.Board(QUIET_FEN)
    after = board.copy()
    after.push_uci("e1d1")
    return FakeAnalyzer(
        {
            QUIET_FEN: _analysis(board, "e2e4", best_cp, None),
            after.fen(): _analysis(after, "e8d8", after_cp, None),
        }
    )


@pytest.mark.parametrize("move", ["e1e8", "Re8#", "Re8", " e1e8 "])
def test_a_move_is_accepted_as_uci_or_san(move: str) -> None:
    """The student may type either notation; both name the same move."""
    board = chess.Board(MATE_FEN)
    analyzer = FakeAnalyzer({MATE_FEN: _analysis(board, "e1e8", None, 1)})
    result = evaluate_move(analyzer, MATE_FEN, move)
    assert result.move_uci == "e1e8"
    assert result.move_san == "Re8#"  # SAN is rendered from the original position


@pytest.mark.parametrize(
    ("cp_loss", "verdict"),
    [
        (0, "good"),  # not the engine's move, but gives up nothing
        (49, "good"),
        (50, "inaccuracy"),  # boundary: inclusive lower edge
        (99, "inaccuracy"),
        (100, "mistake"),
        (299, "mistake"),
        (300, "blunder"),
        (900, "blunder"),
    ],
)
def test_the_verdict_scale_turns_centipawn_loss_into_a_word(
    cp_loss: int, verdict: str
) -> None:
    """The grading boundaries are a teaching decision — pin them exactly."""
    result = evaluate_move(_quiet_analyzer(cp_loss, 0), QUIET_FEN, "e1d1")
    assert result.cp_loss == cp_loss
    assert result.verdict == verdict
    assert result.is_best is False


def test_a_move_better_than_the_engines_best_never_scores_a_negative_loss() -> None:
    """Invariant: cp_loss is a *loss*, so it floors at zero even if the child search
    disagrees with the parent (different depths can do this in the real engine)."""
    result = evaluate_move(_quiet_analyzer(10, -80), QUIET_FEN, "e1d1")
    assert result.cp_loss == 0
    assert result.verdict == "good"


def test_a_move_that_stalemates_is_scored_as_a_draw_without_asking_the_engine() -> None:
    """Terminal branch: the child is a finished game, so no analysis is requested.

    The fake analyzer raises on any unexpected FEN, so this passing proves the
    engine was never consulted for the stalemated position.
    """
    fen = "7k/8/8/8/8/8/5Q2/6K1 w - - 0 1"
    board = chess.Board(fen)
    stalemating = board.parse_san("Qf7")
    after = board.copy()
    after.push(stalemating)
    assert after.is_stalemate(), "fixture must actually stalemate"

    analyzer = FakeAnalyzer({fen: _analysis(board, "f2f8", None, 1)})  # mate available
    result = evaluate_move(analyzer, fen, "Qf7")
    assert result.score_text == "+0.00"  # a draw, from the mover's point of view
    assert result.verdict == "blunder"  # threw away a mate in 1
    assert result.cp_loss == 2000  # capped mate-scale collapse


def test_a_mate_against_us_is_reported_from_the_movers_point_of_view() -> None:
    """The child is scored for the opponent; a mate *for* them is a mate against us."""
    board = chess.Board(QUIET_FEN)
    after = board.copy()
    after.push_uci("e1d1")
    analyzer = FakeAnalyzer(
        {
            QUIET_FEN: _analysis(board, "e2e4", 50, None),
            after.fen(): _analysis(after, "e8d8", None, 3),  # opponent mates in 3
        }
    )
    result = evaluate_move(analyzer, QUIET_FEN, "e1d1")
    assert result.score_text == "#-3"
    assert result.verdict == "blunder"


def test_evaluate_move_rejects_an_illegal_position() -> None:
    with pytest.raises(ValueError):
        evaluate_move(FakeAnalyzer({}), "8/8/8/8/8/8/8/8 w - - 0 1", "e2e4")


# -- the "why not": what happens after the move ------------------------------------


def test_a_losing_move_reports_the_reply_that_punishes_it() -> None:
    """'It's a blunder' is a grade; 'because Kd8 wins the rook' is a reason.

    The centipawn loss says how far from best the move is — a fact about the *other*
    move. What the student asked is what happens to *theirs*, which is the opponent's
    best reply and the line that follows.
    """
    board = chess.Board(QUIET_FEN)
    after = board.copy()
    after.push_uci("e1d1")
    analyzer = FakeAnalyzer(
        {
            QUIET_FEN: _analysis(board, "e2e4", 120, None),
            after.fen(): _analysis(
                after, "e8d8", 300, None, pv_san=("Kd8", "Kc1", "Kc7")
            ),
        }
    )
    result = evaluate_move(analyzer, QUIET_FEN, "e1d1")

    assert result.reply_san == "Kd8"
    assert result.line_san == ("Kd8", "Kc1", "Kc7")


def test_the_best_move_also_gets_its_continuation() -> None:
    """A sound move needs its justification, not just a pass mark.

    The old contract short-circuited here and returned ``cp_loss=0`` with nothing
    else, so "why is my move good?" had no engine-backed answer to draw on.
    """
    board = chess.Board(QUIET_FEN)
    after = board.copy()
    after.push_uci("e2e4")
    analyzer = FakeAnalyzer(
        {
            QUIET_FEN: _analysis(board, "e2e4", 120, None),
            after.fen(): _analysis(after, "e8d8", -120, None, pv_san=("Kd8", "Ke2")),
        }
    )
    result = evaluate_move(analyzer, QUIET_FEN, "e2e4")

    assert result.is_best and result.cp_loss == 0
    assert result.line_san == ("Kd8", "Ke2")


def test_the_best_moves_score_still_comes_from_the_parent_search() -> None:
    """Its own search is the authority on its value; the child only supplies the line.

    Taking the score from the child would compare two searches at different depths
    and could report a non-zero loss for the engine's own choice.
    """
    board = chess.Board(QUIET_FEN)
    after = board.copy()
    after.push_uci("e2e4")
    analyzer = FakeAnalyzer(
        {
            QUIET_FEN: _analysis(board, "e2e4", 120, None),
            # Deliberately inconsistent child: a deeper search that disagrees.
            after.fen(): _analysis(after, "e8d8", -60, None, pv_san=("Kd8",)),
        }
    )
    result = evaluate_move(analyzer, QUIET_FEN, "e2e4")

    assert result.cp_loss == 0
    assert result.score_text == "+1.20"  # the parent's reading, not the child's


class _CountingAnalyzer:
    """Wraps a FakeAnalyzer and counts how many searches it is asked for."""

    def __init__(self, inner: FakeAnalyzer) -> None:
        self._inner = inner
        self.calls = 0

    def analyze(self, fen: str) -> PositionAnalysis:
        self.calls += 1
        return self._inner.analyze(fen)


def test_scoring_a_move_costs_exactly_two_searches() -> None:
    """The engine budget of the tool, pinned.

    Two searches — the position, then the position after the move — and no more.
    The second one is what carries the reply and the line, so it pays for the
    explanation as well as the score rather than being an extra cost on top.
    A third would double the tool's latency inside a live coaching turn.
    """
    board = chess.Board(QUIET_FEN)
    after = board.copy()
    after.push_uci("e1d1")
    counting = _CountingAnalyzer(
        FakeAnalyzer(
            {
                QUIET_FEN: _analysis(board, "e2e4", 120, None),
                after.fen(): _analysis(after, "e8d8", 30, None, pv_san=("Kd8",)),
            }
        )
    )
    evaluate_move(counting, QUIET_FEN, "e1d1")
    assert counting.calls == 2


def test_the_best_move_costs_one_extra_search_than_it_used_to() -> None:
    """The price of giving a sound move its justification, stated openly.

    The old contract returned after a single search here. Explaining *why* the move
    is good needs the position it reaches, so this case now costs two — the same as
    every other move, and the reason a best-move evaluation is the only one that got
    slower.
    """
    board = chess.Board(QUIET_FEN)
    after = board.copy()
    after.push_uci("e2e4")
    counting = _CountingAnalyzer(
        FakeAnalyzer(
            {
                QUIET_FEN: _analysis(board, "e2e4", 120, None),
                after.fen(): _analysis(after, "e8d8", -120, None, pv_san=("Kd8",)),
            }
        )
    )
    result = evaluate_move(counting, QUIET_FEN, "e2e4")
    assert result.is_best and counting.calls == 2


def test_a_terminal_move_still_costs_only_the_one_search() -> None:
    """A finished game has nothing to search, so mate must not pay for a second."""
    board = chess.Board(MATE_FEN)
    counting = _CountingAnalyzer(
        FakeAnalyzer({MATE_FEN: _analysis(board, "g1h1", None, 1)})
    )
    evaluate_move(counting, MATE_FEN, "e1e8")
    assert counting.calls == 1


def test_a_move_that_delivers_mate_has_no_reply() -> None:
    board = chess.Board(MATE_FEN)
    analyzer = FakeAnalyzer({MATE_FEN: _analysis(board, "g1h1", None, 1)})
    result = evaluate_move(analyzer, MATE_FEN, "e1e8")

    assert result.reply_san == ""
    assert result.line_san == ()


# -- compare_candidates -------------------------------------------------------------


def test_candidates_are_ranked_best_first() -> None:
    fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    board = chess.Board(fen)
    passive = board.copy()
    passive.push_uci("e1d1")
    pushed = board.copy()
    pushed.push_uci("e2e4")
    analyzer = FakeAnalyzer(
        {
            fen: _analysis(board, "e2e4", 120, None),
            passive.fen(): _analysis(passive, "e8d8", 30, None),
            # The best candidate is probed too now — it needs its own line.
            pushed.fen(): _analysis(pushed, "e8d8", -120, None),
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

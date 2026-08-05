"""Unit tests for the deterministic metrics (no engine, no network).

Synthetic goldens and results exercise the grading logic directly, so these run
fast and offline regardless of which coach task is selected.
"""

from __future__ import annotations

from evals.data.loader import to_test_case
from evals.data.schema import ChessGolden
from evals.harness.task import CoachResult
from evals.metrics import (
    BestMoveMetric,
    ConversationPolicyMetric,
    DeepLineMetric,
    EndgameTechniqueMetric,
    EvalBucketMetric,
)
from evals.metrics._base import DeterministicMetric

STARTPOS = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KQ_ENDGAME = "8/8/8/4k3/8/3Q4/4K3/8 w - - 0 1"


def _score(
    metric: DeterministicMetric, golden: ChessGolden, result: CoachResult
) -> float:
    return metric.measure(to_test_case(golden, result))


def _best_move_golden() -> ChessGolden:
    return ChessGolden.model_validate(
        {
            "id": "bm",
            "source": "t",
            "fen": STARTPOS,
            "task": "best_move",
            "solution_moves": ["e4"],
            "extraction": {"method": "hand"},
        }
    )


def test_best_move_exact_match_and_san_uci_equivalence() -> None:
    golden = _best_move_golden()
    assert _score(BestMoveMetric(), golden, CoachResult(best_move="e2e4")) == 1.0
    assert _score(BestMoveMetric(), golden, CoachResult(best_move="e4")) == 1.0


def test_best_move_wrong_and_missing_and_illegal() -> None:
    golden = _best_move_golden()
    assert _score(BestMoveMetric(), golden, CoachResult(best_move="d4")) == 0.0
    assert _score(BestMoveMetric(), golden, CoachResult(best_move=None)) == 0.0
    assert _score(BestMoveMetric(), golden, CoachResult(best_move="e2e5")) == 0.0


def _eval_golden() -> ChessGolden:
    return ChessGolden.model_validate(
        {
            "id": "ev",
            "source": "t",
            "fen": STARTPOS,
            "task": "eval_bucket",
            "expected_bucket": "equal",
            "extraction": {"method": "hand"},
        }
    )


def test_eval_bucket_exact_and_tolerance() -> None:
    golden = _eval_golden()
    assert _score(EvalBucketMetric(), golden, CoachResult(eval_bucket="equal")) == 1.0
    assert _score(EvalBucketMetric(), golden, CoachResult(eval_bucket="winning")) == 0.0
    lenient = EvalBucketMetric(tolerance=1)
    assert _score(lenient, golden, CoachResult(eval_bucket="better")) == 1.0
    assert _score(lenient, golden, CoachResult(eval_bucket="winning")) == 0.0


def _endgame_golden() -> ChessGolden:
    return ChessGolden.model_validate(
        {
            "id": "eg",
            "source": "t",
            "fen": KQ_ENDGAME,
            "task": "endgame",
            "solution_moves": ["Qd6"],
            "expected_result": "win",
            "extraction": {"method": "hand"},
        }
    )


def test_endgame_full_partial_and_zero() -> None:
    golden = _endgame_golden()
    both = CoachResult(best_move="Qd6", result="win")
    assert _score(EndgameTechniqueMetric(), golden, both) == 1.0
    move_only = CoachResult(best_move="Qd6", result="draw")
    assert _score(EndgameTechniqueMetric(), golden, move_only) == 0.5
    result_only = CoachResult(best_move="Ke3", result="win")
    assert _score(EndgameTechniqueMetric(), golden, result_only) == 0.5
    neither = CoachResult(best_move="Ke3", result="loss")
    assert _score(EndgameTechniqueMetric(), golden, neither) == 0.0


def _deep_line_golden() -> ChessGolden:
    return ChessGolden.model_validate(
        {
            "id": "dl",
            "source": "t",
            "fen": STARTPOS,
            "task": "deep_line",
            "expected_line": ["e4", "e5", "Nf3"],
            "student_message": "Calculate a short line.",
            "reference_explanation": (
                "White occupies the center, Black contests it, and White develops "
                "with tempo toward the center."
            ),
            "key_ideas": ["center", "development"],
            "extraction": {"method": "hand"},
        }
    )


def test_deep_line_full_partial_missing_and_illegal() -> None:
    golden = _deep_line_golden()
    assert (
        _score(DeepLineMetric(), golden, CoachResult(line=["e2e4", "e7e5", "g1f3"]))
        == 1.0
    )
    assert _score(DeepLineMetric(), golden, CoachResult(best_move="e4")) == 0.5
    assert _score(DeepLineMetric(), golden, CoachResult(line=[])) == 0.0
    assert _score(DeepLineMetric(), golden, CoachResult(line=["e2e5"])) == 0.0


def _conversation_golden(**overrides: object) -> ChessGolden:
    base: dict[str, object] = {
        "id": "conv",
        "source": "t",
        "task": "conversation",
        "conversation_history": [
            {"role": "student", "text": "I want to push my f-pawn."},
            {"role": "coach", "text": "Check your pieces first."},
        ],
        "student_message": "What should I do instead?",
        "reference_explanation": "Improve pieces before committing pawns.",
        "key_ideas": ["improve pieces before pawn pushes"],
        "required_facts": ["improve pieces", "pawn push"],
        "forbidden_claims": ["always push the f-pawn"],
        "spoiler_policy": "none",
        "extraction": {"method": "paraphrased"},
    }
    base.update(overrides)
    return ChessGolden.model_validate(base)


def test_conversation_policy_passes_required_facts() -> None:
    golden = _conversation_golden()
    result = CoachResult(
        explanation="Improve pieces first; the pawn push can wait until it helps them."
    )
    assert _score(ConversationPolicyMetric(), golden, result) == 1.0


def test_conversation_policy_fails_missing_and_forbidden_text() -> None:
    golden = _conversation_golden()
    result = CoachResult(explanation="Always push the f-pawn and attack.")
    score = _score(ConversationPolicyMetric(), golden, result)
    assert 0.0 <= score < 1.0


def test_conversation_policy_enforces_spoiler_withhold() -> None:
    golden = _conversation_golden(
        fen=STARTPOS,
        solution_moves=["e4"],
        required_facts=[],
        forbidden_claims=[],
        spoiler_policy="withhold",
    )
    assert (
        _score(
            ConversationPolicyMetric(),
            golden,
            CoachResult(explanation="Look for a central pawn move."),
        )
        == 1.0
    )
    assert (
        _score(
            ConversationPolicyMetric(),
            golden,
            CoachResult(explanation="The answer is e4."),
        )
        == 0.0
    )

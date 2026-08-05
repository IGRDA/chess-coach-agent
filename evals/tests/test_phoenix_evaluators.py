"""Phoenix evaluators reuse the metrics: correct answers pass, wrong ones fail.

Network-free: the deterministic evaluators call no model, and the LLM-judge evaluators
are only exercised for their attach/skip gating (never invoked here).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from evals.data.loader import load_goldens
from evals.data.schema import ChessGolden
from evals.phoenix import evaluators as ev
from evals.phoenix.dataset import _example

_BUCKETS = {"winning", "better", "equal", "worse", "losing"}


def _example_stub(golden: ChessGolden) -> SimpleNamespace:
    """A stand-in for Phoenix's DatasetExample: just the `.metadata` mapping."""
    return SimpleNamespace(metadata=_example(golden)["metadata"])


def test_exact_match_best_move() -> None:
    golden = load_goldens("best_move")[0]
    example = _example_stub(golden)

    good = ev.exact_match({"best_move": golden.solution_moves[0]}, example)
    assert good["score"] == 1.0
    assert good["label"] == "pass"
    assert good["explanation"]

    bad = ev.exact_match({"best_move": "a1a1"}, example)
    assert bad["score"] == 0.0
    assert bad["label"] == "fail"


def test_exact_match_eval_bucket() -> None:
    golden = load_goldens("eval_bucket")[0]
    example = _example_stub(golden)

    right = ev.exact_match({"eval_bucket": golden.expected_bucket}, example)
    assert right["score"] == 1.0
    wrong = sorted(_BUCKETS - {golden.expected_bucket})[0]
    assert ev.exact_match({"eval_bucket": wrong}, example)["score"] == 0.0


def test_exact_match_endgame_needs_move_and_result() -> None:
    golden = load_goldens("endgame")[0]
    example = _example_stub(golden)

    good = ev.exact_match(
        {"best_move": golden.solution_moves[0], "result": golden.expected_result},
        example,
    )
    assert good["score"] == 1.0

    wrong_result = "win" if golden.expected_result != "win" else "loss"
    bad = ev.exact_match({"best_move": "a1a1", "result": wrong_result}, example)
    assert bad["score"] == 0.0


def test_evaluators_for_gates_the_judges_on_the_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ev.evaluators_for("best_move") == [ev.exact_match]
    assert ev.evaluators_for("teaching") == []

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert ev.evaluators_for("teaching") == [ev.teaching_quality]
    structured = ev.evaluators_for("best_move")
    assert ev.exact_match in structured and ev.explanation_quality in structured

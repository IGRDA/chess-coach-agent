"""Tests for the extraction *validation gate* (offline; no vision, no PDF).

The vision call and page rendering are human-run and network-bound, but the gate
that decides whether an extraction becomes a golden — legality plus engine
agreement — is pure and local, so it is worth guarding here.
"""

from __future__ import annotations

import pytest

from evals.harness.engine import StockfishOracle
from evals.tools.extract_problems import Extracted, ManifestEntry, build_golden

MATE_FEN = "5k2/R7/5K2/8/8/8/8/8 w - - 0 1"  # 1.Ra8#
DRAW_ENDGAME_FEN = "8/8/8/4k3/8/8/4KB2/8 w - - 0 1"  # K+B vs K, insufficient


def _entry(**overrides: object) -> ManifestEntry:
    base: dict[str, object] = {
        "id": "x",
        "book": "Book.pdf",
        "page": 1,
        "task": "best_move",
    }
    base.update(overrides)
    return ManifestEntry(**base)  # type: ignore[arg-type]


def test_engine_agreeing_extraction_is_accepted(oracle: StockfishOracle) -> None:
    golden, reasons = build_golden(
        _entry(theme=["back-rank"]),
        Extracted(fen=MATE_FEN, solution=["Ra8"], confidence=0.9),
        oracle,
    )
    assert golden is not None and not reasons
    assert golden.solution_moves == ["a7a8"]
    assert golden.extraction.method == "vision"


def test_engine_disagreement_is_quarantined(oracle: StockfishOracle) -> None:
    # A legal but non-best move: engine will not agree it is the solution.
    golden, reasons = build_golden(
        _entry(),
        Extracted(fen=MATE_FEN, solution=["Kf5"], confidence=0.9),
        oracle,
    )
    assert golden is None
    assert any("engine best" in r for r in reasons)


@pytest.mark.parametrize(
    ("extracted", "needle"),
    [
        (Extracted(fen="garbage", solution=["Ra8"], confidence=0.9), "illegal FEN"),
        (Extracted(fen=MATE_FEN, solution=["Ra8"], confidence=0.1), "low confidence"),
    ],
)
def test_bad_extractions_are_quarantined(
    oracle: StockfishOracle, extracted: Extracted, needle: str
) -> None:
    golden, reasons = build_golden(_entry(), extracted, oracle)
    assert golden is None
    assert any(needle in r for r in reasons)


def test_eval_bucket_extraction_takes_engine_bucket(oracle: StockfishOracle) -> None:
    golden, reasons = build_golden(
        _entry(task="eval_bucket"),
        Extracted(fen=MATE_FEN, solution=[], confidence=0.9),
        oracle,
    )
    assert golden is not None and not reasons
    assert golden.expected_bucket == "winning"
    assert golden.solution_moves == []


def test_endgame_result_must_match_engine(oracle: StockfishOracle) -> None:
    # Claiming a win in a dead-drawn K+B vs K must be rejected.
    golden, reasons = build_golden(
        _entry(task="endgame", expected_result="win"),
        Extracted(fen=DRAW_ENDGAME_FEN, solution=["Kd3"], confidence=0.9),
        oracle,
    )
    assert golden is None
    assert any("result" in r for r in reasons)

"""The in-process latency/token sampler and its percentile maths.

Fast and backend-free by construction: the sampler exists precisely so a p50/p90
question can be answered without a collector, so these tests need nothing but the
module itself.
"""

from __future__ import annotations

import pytest

from chess_coach.adapters.observability.latency import (
    MAX_SAMPLES,
    Sampler,
    percentile,
)


# -- percentile ---------------------------------------------------------------------


def test_percentile_of_an_empty_sample_is_zero() -> None:
    assert percentile([], 0.5) == 0.0


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        (0.0, 1.0),  # the floor is the smallest observation
        (0.5, 5.0),
        (0.9, 9.0),
        (1.0, 10.0),
    ],
)
def test_percentile_returns_an_observed_value(q: float, expected: float) -> None:
    """Nearest-rank: every percentile is a measurement that actually happened."""
    samples = [float(n) for n in range(1, 11)]  # 1..10
    assert percentile(samples, q) == expected


def test_percentile_does_not_care_about_input_order() -> None:
    assert percentile([9.0, 1.0, 5.0, 3.0, 7.0], 0.5) == 5.0


def test_percentile_rejects_a_quantile_outside_the_unit_interval() -> None:
    with pytest.raises(ValueError):
        percentile([1.0], 1.5)


def test_a_single_sample_is_every_percentile() -> None:
    assert percentile([4.2], 0.5) == percentile([4.2], 0.9) == 4.2


# -- Sampler ------------------------------------------------------------------------


def test_samples_are_bucketed_by_name() -> None:
    sampler = Sampler()
    sampler.record("turn", 10.0)
    sampler.record("tool", 1.0)
    sampler.record("turn", 30.0)

    assert sampler.samples("turn") == [10.0, 30.0]
    assert sampler.samples("tool") == [1.0]
    assert sampler.names() == ["tool", "turn"]


def test_an_unknown_name_has_no_samples() -> None:
    assert Sampler().samples("nothing-recorded") == []


def test_summary_reports_the_distribution() -> None:
    sampler = Sampler()
    for value in range(1, 11):
        sampler.record("turn", float(value))

    summary = sampler.summarize("turn")
    assert summary.count == 10
    assert summary.p50 == 5.0
    assert summary.p90 == 9.0
    assert summary.mean == pytest.approx(5.5)
    assert summary.total == pytest.approx(55.0)


def test_the_buffer_is_bounded_and_keeps_the_most_recent_samples() -> None:
    """A long session must not grow without limit; recency is what a benchmark wants."""
    sampler = Sampler()
    for value in range(MAX_SAMPLES + 100):
        sampler.record("turn", float(value))

    kept = sampler.samples("turn")
    assert len(kept) == MAX_SAMPLES
    assert kept[-1] == float(MAX_SAMPLES + 99)  # newest retained
    assert kept[0] == 100.0  # oldest 100 dropped


def test_reset_clears_every_bucket() -> None:
    sampler = Sampler()
    sampler.record("turn", 1.0)
    sampler.reset()
    assert sampler.names() == []


def test_report_is_readable_and_survives_an_empty_sampler() -> None:
    assert "no samples" in Sampler().report()

    sampler = Sampler()
    sampler.record("coach.answer.latency_ms", 12.0)
    report = sampler.report()
    assert "coach.answer.latency_ms" in report
    assert "p50=" in report and "p90=" in report

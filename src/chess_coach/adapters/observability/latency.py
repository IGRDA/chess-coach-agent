"""In-process latency and token sampling — the numbers, without a backend.

:mod:`tracing` exports spans to an OTLP collector, which is the right home for
one turn's detail but the wrong tool for a question like "did p90 get worse?".
That question needs a *distribution*, available in the same process that just ran
the work, with no collector, no network and no optional extra installed. This
module is that: a tiny sampler plus the percentile maths.

Two properties worth naming:

* **It measures wall-clock, so it works for every provider.** The Claude Agent
  SDK reports its own ``duration_ms`` on a ``ResultMessage``; Codex reports
  nothing. A stopwatch around the turn is provider-independent, and it is also
  the number a user actually feels — queueing and engine time included.
* **It is always on and always cheap.** Unlike tracing, there is no enable flag:
  appending a float to a list costs nothing, and a bounded buffer keeps a long
  session from growing without limit.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict
from dataclasses import dataclass, field

# Keep memory flat in a long-lived session: only the most recent samples per name
# are retained, which is all a percentile over a benchmark run needs.
MAX_SAMPLES = 5000


@dataclass(frozen=True)
class Summary:
    """The distribution of one measured operation."""

    name: str
    count: int
    p50: float
    p90: float
    p99: float
    mean: float
    total: float

    def as_row(self) -> str:
        return (
            f"{self.name:<28} n={self.count:<5} "
            f"p50={self.p50:9.1f}  p90={self.p90:9.1f}  p99={self.p99:9.1f}  "
            f"mean={self.mean:9.1f}"
        )


def percentile(samples: list[float], q: float) -> float:
    """The ``q``-quantile (0..1) of ``samples`` by nearest-rank.

    Nearest-rank rather than interpolation on purpose: every value it returns is a
    measurement that actually happened, which is what makes "p90 = 4.2s" a claim
    about a real turn rather than about an average of two turns. Returns ``0.0``
    for an empty sample.
    """
    if not samples:
        return 0.0
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"quantile must be in [0, 1], got {q}")
    ordered = sorted(samples)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


@dataclass
class Sampler:
    """Thread-safe buckets of measurements, keyed by operation name."""

    _samples: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, name: str, value: float) -> None:
        """Add one measurement (milliseconds for latency, count for tokens)."""
        with self._lock:
            bucket = self._samples[name]
            bucket.append(value)
            if len(bucket) > MAX_SAMPLES:
                del bucket[: len(bucket) - MAX_SAMPLES]

    def samples(self, name: str) -> list[float]:
        with self._lock:
            return list(self._samples.get(name, ()))

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._samples)

    def summarize(self, name: str) -> Summary:
        values = self.samples(name)
        count = len(values)
        return Summary(
            name=name,
            count=count,
            p50=percentile(values, 0.50),
            p90=percentile(values, 0.90),
            p99=percentile(values, 0.99),
            mean=(sum(values) / count) if count else 0.0,
            total=sum(values),
        )

    def summaries(self) -> list[Summary]:
        return [self.summarize(name) for name in self.names()]

    def report(self) -> str:
        """A printable table of every measured operation."""
        rows = self.summaries()
        if not rows:
            return "(no samples recorded)"
        return "\n".join(row.as_row() for row in rows)

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()


# The process-wide sampler the coach writes into. Tests and benchmarks call
# ``reset()`` first so one run's numbers cannot leak into the next.
SAMPLER = Sampler()


def record(name: str, value: float) -> None:
    """Record one measurement into the process-wide sampler."""
    SAMPLER.record(name, value)


def report() -> str:
    """A printable table of everything measured so far."""
    return SAMPLER.report()


def reset() -> None:
    """Drop every sample (call before a benchmark run)."""
    SAMPLER.reset()

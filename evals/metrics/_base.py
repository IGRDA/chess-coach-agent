"""Shared plumbing for the deterministic metrics.

``DeterministicMetric`` adapts our exact-match grading to deepeval's
``BaseMetric`` surface: subclasses implement one pure method, ``_evaluate``, that
turns a golden and the coach's result into a (score, reason) pair; the base
handles the deepeval bookkeeping (``score``/``success``/``reason``, the async
shim, naming). These metrics never call a model, so ``a_measure`` just delegates.
"""

from __future__ import annotations

from abc import abstractmethod

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from evals.data.schema import ChessGolden
from evals.harness.task import CoachResult


class DeterministicMetric(BaseMetric):  # type: ignore[no-untyped-call]
    """A deepeval metric graded by exact match, no model involved."""

    def __init__(self, threshold: float = 1.0) -> None:
        self.threshold = threshold
        self.score: float = 0.0
        self.reason: str = ""
        self.success: bool = False
        self.error: str | None = None

    @abstractmethod
    def _evaluate(self, golden: ChessGolden, result: CoachResult) -> tuple[float, str]:
        """Return (score in [0, 1], human reason) for this answer."""

    def measure(self, test_case: LLMTestCase, *args: object, **kwargs: object) -> float:
        meta = test_case.metadata or {}
        golden = meta.get("golden")
        result = meta.get("result")
        if not isinstance(golden, ChessGolden) or not isinstance(result, CoachResult):
            raise ValueError(
                "test case is missing 'golden'/'result' in metadata; "
                "build it with evals.data.loader.to_test_case"
            )
        self.score, self.reason = self._evaluate(golden, result)
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(
        self, test_case: LLMTestCase, *args: object, **kwargs: object
    ) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self) -> str:
        # deepeval reads `__name__` for its reports. Use `__qualname__` (not the
        # overridden `__name__`, which would resolve to this property object).
        return type(self).__qualname__

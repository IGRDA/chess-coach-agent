"""The concrete tasks the eval run selects between.

Two implementations of ``CoachTask`` bracket the framework:

- ``OracleTask`` answers every question from the pinned Stockfish oracle. It is
  the *known-good reference solver*: running the deterministic suite against it
  proves the harness, metrics and dataset are mutually consistent (the suite goes
  green). It is not the system we ultimately grade — it is the yardstick.
- ``PendingAgentTask`` stands in for the real Claude coach, which does not exist
  yet. It raises ``NotImplementedError`` so that selecting it makes the suite fail
  loudly-but-expectedly (xfail) — the standing TDD target the agent must satisfy.

The suite's conftest picks between them from the ``COACH_TASK`` environment
variable.
"""

from __future__ import annotations

from evals.harness.engine import StockfishOracle
from evals.harness.task import CoachInput, CoachResult


class OracleTask:
    """Reference ``CoachTask`` backed by Stockfish — the green baseline."""

    def __init__(self, oracle: StockfishOracle) -> None:
        self._oracle = oracle

    def __call__(self, task_input: CoachInput) -> CoachResult:
        if task_input.task_type == "deep_line":
            raise NotImplementedError(
                "deep_line goldens are book continuations, not single-position "
                "oracle answers; run them against COACH_TASK=agent."
            )
        if task_input.fen is None:
            raise NotImplementedError(
                "The Stockfish oracle cannot answer general chat or conversation turns"
            )
        a = self._oracle.assess(task_input.fen)
        return CoachResult(
            best_move=a.best_move_uci,
            eval_bucket=a.bucket,
            result=a.result(),  # type: ignore[arg-type]
            explanation="",
        )


class PendingAgentTask:
    """Stub for the not-yet-built coach: always raises, marking the TDD target."""

    def __call__(self, task_input: CoachInput) -> CoachResult:
        raise NotImplementedError(
            "The real coach agent is not implemented yet; run the eval suite "
            "against the reference oracle (COACH_TASK=oracle) until it is."
        )

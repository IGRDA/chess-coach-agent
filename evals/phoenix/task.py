"""The coach under evaluation, as a Phoenix experiment task.

Reuses the exact harness the pytest suite drives: a :class:`CoachTask` selected from
``COACH_TASK`` (``oracle`` default, ``agent``, ``pending``) — mirroring
``evals/conftest.py`` — turned into the ``example → output`` function ``run_experiment``
expects. The task is kept a thin wrapper around :func:`phoenix_task`, which is pure and
unit-testable with any :class:`CoachTask` and a plain input mapping (no server, no
engine).

When ``COACH_TASK=agent`` and ``CHESS_COACH_TRACING_ENABLED=1``, the agent's own tool
spans nest under each experiment run automatically via the coach's OTLP tracing.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from evals.harness.engine import StockfishOracle, find_stockfish
from evals.harness.fakes import OracleTask, PendingAgentTask
from evals.harness.task import CoachInput, CoachTask

# Mirrors evals/conftest.py; the system under test is chosen at run time.
COACH_TASK_ENV = "COACH_TASK"

PhoenixTask = Callable[[Mapping[str, Any]], dict[str, Any]]


def phoenix_task(coach: CoachTask) -> PhoenixTask:
    """Wrap a harness :class:`CoachTask` as a Phoenix ``input → output`` function."""

    def task(input: Mapping[str, Any]) -> dict[str, Any]:
        ci = CoachInput(
            fen=input["fen"],
            task_type=input["task"],
            level=input.get("level"),
            context=input.get("student_message"),
        )
        r = coach(ci)
        return {
            "best_move": r.best_move,
            "eval_bucket": r.eval_bucket,
            "result": r.result,
            "explanation": r.explanation,
        }

    return task


def _select(name: str, oracle: StockfishOracle) -> CoachTask:
    """The concrete coach for ``COACH_TASK`` (mirrors ``evals/conftest.py``)."""
    if name == "oracle":
        return OracleTask(oracle)
    if name == "agent":
        from evals.harness.agent_task import AgentTask

        return AgentTask(oracle)
    if name == "pending":
        return PendingAgentTask()
    raise ValueError(
        f"unknown {COACH_TASK_ENV}={name!r}; use 'oracle', 'agent' or 'pending'"
    )


@contextmanager
def coach_task_context() -> Iterator[PhoenixTask]:
    """Yield the Phoenix task, holding a Stockfish oracle open for the whole run."""
    find_stockfish()  # raises EngineUnavailableError with a clear message if missing
    name = os.environ.get(COACH_TASK_ENV, "oracle")
    with StockfishOracle() as oracle:
        yield phoenix_task(_select(name, oracle))

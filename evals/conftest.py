"""Fixtures for the eval suite: the engine and the selected coach task.

The system under test is chosen at run time by the ``COACH_TASK`` environment
variable:

- ``oracle`` (default) grades the Stockfish reference solver and is expected to
  pass — the yardstick that proves the harness.
- ``agent`` grades the real Claude coach (:class:`evals.harness.agent_task.AgentTask`),
  which consults tools and narrates. It needs the ``claude`` CLI; answers are
  cached so re-runs are cheap.
- ``pending`` selects the not-yet-built stub, whose ``NotImplementedError`` xfails
  — kept so the original TDD target stays selectable.

Deterministic tests need only local Stockfish; if no binary is found the
engine-backed tests skip rather than error.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from evals.harness.engine import EngineUnavailableError, StockfishOracle, find_stockfish
from evals.harness.fakes import OracleTask, PendingAgentTask
from evals.harness.task import CoachTask

COACH_TASK_ENV = "COACH_TASK"


def pytest_report_header() -> str:
    return f"eval coach task: {os.environ.get(COACH_TASK_ENV, 'oracle')}"


@pytest.fixture(scope="session")
def oracle() -> Iterator[StockfishOracle]:
    """A session-wide pinned Stockfish oracle; skips if no binary is present."""
    try:
        find_stockfish()
    except EngineUnavailableError as exc:
        pytest.skip(str(exc))
    with StockfishOracle() as engine:
        yield engine


@pytest.fixture(scope="session")
def coach_task(oracle: StockfishOracle) -> CoachTask:
    """The coach under evaluation, selected from ``COACH_TASK``."""
    name = os.environ.get(COACH_TASK_ENV, "oracle")
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

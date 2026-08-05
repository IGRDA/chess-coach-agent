"""The task boundary and ground-truth harness the eval suite drives.

Exposes the pluggable ``CoachTask`` contract (:mod:`evals.harness.task`), the
pinned Stockfish oracle (:mod:`evals.harness.engine`), pure position checkers
(:mod:`evals.harness.checkers`), and the reference/stub tasks
(:mod:`evals.harness.fakes`) selected at run time.
"""

from evals.harness.task import CoachInput, CoachResult, CoachTask, TaskType

__all__ = ["CoachInput", "CoachResult", "CoachTask", "TaskType"]

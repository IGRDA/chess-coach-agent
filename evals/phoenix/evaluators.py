"""Phoenix evaluators that reuse the existing grading verbatim.

Every evaluator here rebuilds the typed :class:`ChessGolden` (from the example's
metadata) and :class:`CoachResult` (from the task output), then delegates to the same
metric the deepeval suite uses — so the Phoenix score and the local score are computed
by identical code. Deterministic tasks use :func:`metric_for`; the ``teaching`` /
explanation judges wrap the deepeval ``GEval`` metrics and only attach when
``ANTHROPIC_API_KEY`` is set (they call a model).

Evaluators return the Phoenix ``EvaluationResult`` dict shape
``{"score", "label", "explanation"}``; params are bound by name (``output``,
``example``) by ``run_experiment``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from evals.data.loader import (
    to_judge_case,
    to_teaching_case,
    to_test_case,
)
from evals.data.schema import ChessGolden
from evals.harness.task import CoachResult, TaskType
from evals.tools.report import metric_for

# A Phoenix evaluator: bound by name to the task output and the dataset example.
Evaluator = Callable[..., dict[str, Any]]


def _rebuild(example: Any, output: Any) -> tuple[ChessGolden, CoachResult]:
    """Reconstruct the graded pair from a Phoenix example + task output."""
    golden = ChessGolden.model_validate(example.metadata["golden"])
    out = output if isinstance(output, dict) else {}
    result = CoachResult(
        best_move=out.get("best_move"),
        eval_bucket=out.get("eval_bucket"),
        result=out.get("result"),
        explanation=out.get("explanation") or "",
    )
    return golden, result


def _result(score: float, success: bool, reason: str) -> dict[str, Any]:
    return {
        "score": float(score),
        "label": "pass" if success else "fail",
        "explanation": reason,
    }


def exact_match(output: Any, example: Any) -> dict[str, Any]:
    """Deterministic grade: the task's structured metric, by exact match."""
    golden, result = _rebuild(example, output)
    metric = metric_for(golden.task)
    metric.measure(to_test_case(golden, result))
    return _result(metric.score, metric.is_successful(), metric.reason)


def explanation_quality(output: Any, example: Any) -> dict[str, Any]:
    """LLM-as-judge over the coach's explanation (needs ANTHROPIC_API_KEY)."""
    from evals.metrics.explanation import explanation_quality_metric

    golden, result = _rebuild(example, output)
    metric = explanation_quality_metric()
    metric.measure(to_judge_case(golden, result))
    return _result(metric.score or 0.0, metric.is_successful(), metric.reason or "")


def teaching_quality(output: Any, example: Any) -> dict[str, Any]:
    """LLM-as-judge over a teaching turn — correctness + spoiler control."""
    from evals.metrics.teaching import teaching_quality_metric

    golden, result = _rebuild(example, output)
    metric = teaching_quality_metric()
    metric.measure(to_teaching_case(golden, result))
    return _result(metric.score or 0.0, metric.is_successful(), metric.reason or "")


def _judging_enabled() -> bool:
    """The LLM judges call a model, so only attach them when a key is present."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def evaluators_for(task: TaskType) -> list[Evaluator]:
    """The evaluators to attach for a task.

    The three structured tasks grade by exact match, plus the explanation judge when a
    key is present. ``teaching`` is prose-only, graded solely by the teaching judge (so
    it yields no evaluators without a key).
    """
    if task == "teaching":
        return [teaching_quality] if _judging_enabled() else []
    evaluators: list[Evaluator] = [exact_match]
    if _judging_enabled():
        evaluators.append(explanation_quality)
    return evaluators

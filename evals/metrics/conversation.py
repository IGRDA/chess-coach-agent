"""Deterministic checks for multi-turn conversation evals.

The LLM judge grades teaching quality and context awareness. This metric catches
cheap objective failures first: empty replies, missing required facts, forbidden
claims, and spoiler-policy violations when a move is known.
"""

from __future__ import annotations

from evals.data.schema import ChessGolden
from evals.harness.task import CoachResult
from evals.metrics._base import DeterministicMetric


class ConversationPolicyMetric(DeterministicMetric):  # type: ignore[no-untyped-call]
    """Score deterministic policy/fact checks for a conversation reply."""

    def _evaluate(self, golden: ChessGolden, result: CoachResult) -> tuple[float, str]:
        text = result.explanation.strip()
        if not text:
            return 0.0, "coach produced no reply"

        lower = text.lower()
        checks: list[tuple[bool, str]] = []
        checks.extend(
            (_contains_fact(lower, fact), f"required fact {fact!r}")
            for fact in golden.required_facts
        )
        checks.extend(
            (claim.lower() not in lower, f"forbidden claim {claim!r}")
            for claim in golden.forbidden_claims
        )

        move_tokens = [m.lower() for m in golden.solution_moves]
        if golden.spoiler_policy == "withhold" and move_tokens:
            checks.append(
                (
                    not any(move in lower for move in move_tokens),
                    "withheld solution move",
                )
            )
        if golden.spoiler_policy == "reveal" and move_tokens:
            checks.append(
                (
                    any(move in lower for move in move_tokens),
                    "revealed solution move",
                )
            )

        if not checks:
            return 1.0, "non-empty conversation reply"
        passed = sum(1 for ok, _ in checks if ok)
        failed = [note for ok, note in checks if not ok]
        score = passed / len(checks)
        reason = (
            "passed deterministic checks"
            if not failed
            else "failed: " + ", ".join(failed)
        )
        return score, reason


def _contains_fact(text: str, fact: str) -> bool:
    """Accept exact required fact text, case-insensitively.

    The dataset keeps these facts short and phrase-like on purpose; semantic
    coverage is handled by the conversation judge.
    """
    return fact.lower() in text

"""The pluggable task boundary the eval suite drives.

The coach under evaluation is reached through one small contract, ``CoachTask``:
a callable that turns a structured ``CoachInput`` (a position plus what is being
asked) into a structured ``CoachResult`` (the move, the assessment, the endgame
result, and a free-text explanation). Keeping the boundary this narrow lets the
whole framework — datasets, metrics, tests — exist and run before the real agent
does: today a Stockfish-backed reference task satisfies it; tomorrow the Claude
coach will.

Grading reads the *structured* fields (exact-match first); the ``explanation``
feeds only the opt-in LLM-as-judge metric.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

TaskType = Literal[
    "best_move",
    "eval_bucket",
    "endgame",
    "deep_line",
    "teaching",
    "mistake_diagnosis",
    "multi_turn_teaching",
    "conversation",
    "general_chat",
]
"""What the coach is being asked to produce for a position.

The first three grade a *structured* field by exact match, and ``deep_line`` grades
a short best-play continuation. The teaching-style tasks (``teaching``,
``mistake_diagnosis``, ``multi_turn_teaching``, ``conversation``) and ``general_chat``
are different: the coach answers a student's utterance in prose, graded by the opt-in
judges (correctness, Socratic quality, diagnosis, spoiler control, coaching quality)
and, for ``conversation``, lightweight deterministic policy checks.
"""

EndgameResult = Literal["win", "draw", "loss"]
"""Game-theoretic result claimed for an endgame, from the side-to-move POV."""


@dataclass(frozen=True)
class CoachInput:
    """One question put to the coach: a position and what to produce for it.

    ``fen`` is a standard FEN for position tasks, and is absent for general chess
    chat. ``task_type`` selects which structured field of the result is graded.
    ``level`` (e.g. ``"beginner"``) and ``context`` are optional hints a real
    coach may use to pitch its answer; the deterministic metrics ignore them.
    """

    fen: str | None
    task_type: TaskType
    level: str | None = None
    context: str | None = None
    candidate_move: str | None = None
    conversation_history: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class CoachResult:
    """The coach's structured answer plus its narration.

    Each field is optional so a task may answer only what was asked: ``best_move``
    (SAN or UCI — the metric normalises both), ``eval_bucket`` (one of the buckets
    in :mod:`evals.harness.checkers`), ``result`` (win/draw/loss for endgames),
    ``line`` (a UCI/SAN continuation for deeper calculation), and ``explanation``
    (prose, graded only by the opt-in judge).
    """

    best_move: str | None = None
    eval_bucket: str | None = None
    result: EndgameResult | None = None
    line: list[str] | None = None
    explanation: str = ""


@runtime_checkable
class CoachTask(Protocol):
    """The system under test: position in, structured answer out.

    Implemented today by the reference and stub tasks in
    :mod:`evals.harness.fakes`; later by the real Claude coach adapter. The eval
    run selects the concrete task (see ``COACH_TASK`` in the suite's conftest).
    """

    def __call__(self, task_input: CoachInput) -> CoachResult: ...

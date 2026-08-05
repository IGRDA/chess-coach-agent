"""Data transfer objects for use-case inputs and outputs.

The request and result shapes that cross the application boundary. Use cases
accept request DTOs and return result DTOs so the delivery layer (the CLI today,
other front-ends tomorrow) never touches raw domain entities, and so the shape of
each interaction is documented in one place. DTOs are plain, immutable data
holders — values, never behaviour, and no library-specific types.

Tracing-bullet slice: the coach-a-position interaction. A
:class:`CoachingRequest` names the position (FEN), what is being asked (task) and
who is asking (level); a :class:`CoachingResult` is the engine-grounded answer the
coach reports back. Both are engine/SDK-agnostic — the adapter maps its own
structures onto these.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoachingRequest:
    """What to coach: a position, the question asked of it, and for whom.

    ``task`` is one of the coaching tasks (``best_move``, ``eval_bucket``,
    ``endgame``, ``explain``, ``deep_line``); ``level`` is an optional free-form
    audience hint (e.g. ``"beginner"``) that tunes the explanation's pitch.

    ``question`` and ``candidate_move`` are the free-form channel: a question the
    student typed (e.g. "what are the candidate moves?") and a move they are
    weighing (UCI or SAN) that the coach should ground and critique. Both are
    optional so the structured tasks stay a bare ``(fen, task)`` call.
    """

    fen: str
    task: str
    level: str | None = None
    question: str | None = None
    candidate_move: str | None = None


@dataclass(frozen=True)
class CoachingResult:
    """The coach's engine-grounded answer, ready to present.

    Only the fields relevant to the task are populated; the rest are ``None``.
    ``best_move`` is UCI, ``eval_bucket`` is a coarse assessment bucket,
    ``result`` is a win/draw/loss verdict, ``line`` is a UCI continuation, and
    ``explanation`` is the coach's prose.
    """

    best_move: str | None
    eval_bucket: str | None
    result: str | None
    explanation: str
    line: list[str] | None = None

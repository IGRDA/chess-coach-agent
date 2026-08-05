"""The golden record: one validated, graded chess problem or chat prompt.

``ChessGolden`` is the single shape every problem in the dataset takes, whatever
book or task it came from. Its validators enforce the invariants the rest of the
framework depends on — a legal FEN for position tasks, legal solution moves, and
the presence of the ground-truth field the task actually grades — so a malformed
problem fails at load time rather than skewing a score. Provenance (which book,
which page, how it was extracted) travels with each record for auditability and
regeneration.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from evals.harness.checkers import BUCKETS, is_legal_move, is_valid_fen, normalize_move
from evals.harness.task import EndgameResult, TaskType

_LEVELS = ("beginner", "intermediate", "advanced", "expert")
_ROLES = ("student", "coach")
_SPOILER_POLICIES = ("none", "withhold", "reveal")


class Extraction(BaseModel):
    """How a golden's position was obtained, for audit and regeneration."""

    method: str = Field(description="e.g. 'vision', 'hand'")
    model: str | None = Field(default=None, description="vision model id, if any")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    validated_by: list[str] = Field(
        default_factory=list,
        description="checks that passed, e.g. ['python-chess', 'stockfish']",
    )


class ConversationTurn(BaseModel):
    """One expected student/coach exchange inside a multi-turn teaching golden."""

    model_config = {"frozen": True, "extra": "forbid"}

    student: str = Field(min_length=1)
    expected_coach_behavior: str = Field(
        min_length=1,
        description="what a strong coach should do on this turn",
    )
    reveal_allowed: bool = Field(
        default=False,
        description="whether the coach may state the concrete answer on this turn",
    )
    must_include: list[str] = Field(
        default_factory=list,
        description="ideas, phrases or facts a good answer should include",
    )
    must_not_include: list[str] = Field(
        default_factory=list,
        description="answers or spoilers that should not appear on this turn",
    )


class HistoryTurn(BaseModel):
    """One turn in a stored teacher-student conversation history."""

    role: Literal["student", "coach"]
    text: str = Field(min_length=1)


class ChessGolden(BaseModel):
    """One graded problem/chat prompt: input + task + ground truth + provenance."""

    model_config = {"frozen": True, "extra": "forbid"}

    id: str = Field(min_length=1)
    source: str = Field(min_length=1, description="book title + page/problem")
    fen: str | None = None
    task: TaskType
    solution_moves: list[str] = Field(
        default_factory=list,
        description="accepted best/key moves (SAN or UCI); for best_move & endgame",
    )
    expected_line: list[str] = Field(
        default_factory=list,
        description="accepted main continuation (SAN or UCI); for deep_line",
    )
    expected_bucket: str | None = Field(
        default=None, description="ground-truth assessment bucket; for eval_bucket"
    )
    expected_result: EndgameResult | None = Field(
        default=None, description="win/draw/loss; for endgame"
    )
    reference_explanation: str | None = Field(
        default=None,
        description="the book's own explanation of the position — ground truth "
        "for judging the coach's prose (not just the engine move)",
    )
    key_ideas: list[str] = Field(
        default_factory=list,
        description="the essential points the book makes (e.g. 'zugzwang', 'cut "
        "off the king'); anchors for the explanation judge",
    )
    student_message: str | None = Field(
        default=None,
        description="what the student says to the coach; the input for a teaching turn",
    )
    student_move: str | None = Field(
        default=None,
        description="the move the student played or proposes; for mistake diagnosis",
    )
    engine_best_move: str | None = Field(
        default=None,
        description="engine-best move in this position; for mistake diagnosis",
    )
    engine_refutation: str | None = Field(
        default=None,
        description="engine-backed line or concrete punishment of the student move",
    )
    expected_weakness_tags: list[str] = Field(
        default_factory=list,
        description="student weakness labels the coach should diagnose",
    )
    conversation: list[ConversationTurn] = Field(
        default_factory=list,
        description="expected turn-by-turn behavior for multi-turn teaching evals",
    )
    expected_reveal_turn: int | None = Field(
        default=None,
        ge=1,
        description="first coach turn where stating the answer is allowed",
    )
    spoiler_forbidden: bool = Field(
        default=False,
        description="for teaching: the student asked for a hint, so the coach must "
        "guide without stating the best move outright",
    )
    conversation_history: list[HistoryTurn] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    spoiler_policy: str = Field(default="none")
    theme: list[str] = Field(default_factory=list)
    level: str = Field(default="intermediate")
    extraction: Extraction

    @field_validator("fen")
    @classmethod
    def _fen_is_legal(cls, fen: str | None) -> str | None:
        if fen is not None and not is_valid_fen(fen):
            raise ValueError(f"illegal FEN: {fen!r}")
        return fen

    @field_validator("level")
    @classmethod
    def _known_level(cls, level: str) -> str:
        if level not in _LEVELS:
            raise ValueError(f"level must be one of {_LEVELS}, got {level!r}")
        return level

    @field_validator("expected_bucket")
    @classmethod
    def _known_bucket(cls, bucket: str | None) -> str | None:
        if bucket is not None and bucket not in BUCKETS:
            raise ValueError(
                f"expected_bucket must be one of {BUCKETS}, got {bucket!r}"
            )
        return bucket

    @field_validator("spoiler_policy")
    @classmethod
    def _known_spoiler_policy(cls, policy: str) -> str:
        if policy not in _SPOILER_POLICIES:
            raise ValueError(
                f"spoiler_policy must be one of {_SPOILER_POLICIES}, got {policy!r}"
            )
        return policy

    @model_validator(mode="after")
    def _moves_legal_in_position(self) -> ChessGolden:
        if self.fen is None:
            if self.solution_moves:
                raise ValueError("solution moves require a FEN")
            return self
        fen = self.fen
        for move in self.solution_moves:
            if not is_legal_move(fen, move):
                raise ValueError(f"solution move {move!r} illegal in {fen!r}")
        for label, candidate in (
            ("student_move", self.student_move),
            ("engine_best_move", self.engine_best_move),
        ):
            if candidate is not None and not is_legal_move(fen, candidate):
                raise ValueError(f"{label} {candidate!r} illegal in {fen!r}")
        return self

    @model_validator(mode="after")
    def _line_legal_in_sequence(self) -> ChessGolden:
        if self.fen is None:
            if self.expected_line:
                raise ValueError("expected_line requires a FEN")
            return self
        fen = self.fen
        for move in self.expected_line:
            try:
                normalize_move(fen, move)
            except ValueError as exc:
                raise ValueError(
                    f"expected line move {move!r} illegal after {fen!r}"
                ) from exc

            # Avoid importing chess at module import sites that do not need the
            # sequence validator; this path only runs when records are loaded.
            import chess

            board = chess.Board(fen)
            board.push(chess.Move.from_uci(normalize_move(fen, move)))
            fen = board.fen()
        return self

    @field_validator("reference_explanation")
    @classmethod
    def _explanation_non_empty(cls, text: str | None) -> str | None:
        if text is not None and not text.strip():
            raise ValueError("reference_explanation, if given, must be non-empty")
        return text

    @model_validator(mode="after")
    def _ground_truth_matches_task(self) -> ChessGolden:
        """Every golden must carry the ground truth its task is graded on."""
        if (
            self.task in {"best_move", "eval_bucket", "endgame", "teaching"}
            and self.fen is None
        ):
            raise ValueError(f"{self.task} golden needs a FEN")
        if self.task == "best_move" and not self.solution_moves:
            raise ValueError("best_move golden needs at least one solution move")
        if self.task == "eval_bucket" and self.expected_bucket is None:
            raise ValueError("eval_bucket golden needs an expected_bucket")
        if self.task == "endgame" and (
            not self.solution_moves or self.expected_result is None
        ):
            raise ValueError("endgame golden needs solution_moves and expected_result")
        if self.task == "teaching" and (
            not self.student_message or not self.reference_explanation
        ):
            raise ValueError(
                "teaching golden needs a student_message and a reference_explanation"
            )
        if self.task == "mistake_diagnosis" and (
            not self.student_message
            or not self.student_move
            or not self.engine_best_move
            or not self.engine_refutation
            or not self.expected_weakness_tags
            or not self.reference_explanation
        ):
            raise ValueError(
                "mistake_diagnosis golden needs student_message, student_move, "
                "engine_best_move, engine_refutation, expected_weakness_tags "
                "and reference_explanation"
            )
        if self.task == "multi_turn_teaching":
            if len(self.conversation) < 2 or not self.reference_explanation:
                raise ValueError(
                    "multi_turn_teaching golden needs at least two conversation "
                    "turns and a reference_explanation"
                )
            reveal_turn = self.expected_reveal_turn
            if reveal_turn is not None and reveal_turn > len(self.conversation):
                raise ValueError(
                    "expected_reveal_turn cannot be after the last conversation turn"
                )
        if self.task == "deep_line" and (
            not self.expected_line
            or not self.student_message
            or not self.reference_explanation
            or not self.key_ideas
        ):
            raise ValueError(
                "deep_line golden needs expected_line, student_message, "
                "reference_explanation and key_ideas"
            )
        if self.task == "general_chat" and (
            self.fen is not None
            or not self.student_message
            or not self.reference_explanation
            or not self.key_ideas
        ):
            raise ValueError(
                "general_chat golden needs no FEN, plus a student_message, "
                "reference_explanation and key_ideas"
            )
        if self.task == "conversation" and (
            not self.student_message
            or not self.reference_explanation
            or not self.key_ideas
            or not self.conversation_history
        ):
            raise ValueError(
                "conversation golden needs a student_message, conversation_history, "
                "reference_explanation and key_ideas"
            )
        return self

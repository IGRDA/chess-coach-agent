"""Load and validate goldens, and bridge them to deepeval test cases.

Reads every ``goldens/*.json`` file into validated ``ChessGolden`` records (a
parse error or a broken invariant raises here, at load time) and offers the two
small adapters the suite needs: turning a golden into the ``CoachInput`` posed to
the task, and pairing a golden with the coach's ``CoachResult`` into a deepeval
``LLMTestCase``. The structured ground truth and the raw result ride along in the
test case's ``metadata`` so the deterministic metrics grade fields, not prose.
"""

from __future__ import annotations

import json
from pathlib import Path

from deepeval.test_case import LLMTestCase

from evals.data.schema import ChessGolden
from evals.harness.task import CoachInput, CoachResult, TaskType

GOLDENS_DIR = Path(__file__).parent / "goldens"


def load_goldens(
    task: TaskType | None = None, *, goldens_dir: Path = GOLDENS_DIR
) -> list[ChessGolden]:
    """Load all goldens (optionally filtered to one task), sorted by id.

    Raises ``pydantic.ValidationError`` if any record violates the schema, and
    ``ValueError`` on duplicate ids across files.
    """
    goldens: list[ChessGolden] = []
    for path in sorted(goldens_dir.glob("*.json")):
        raw = json.loads(path.read_text())
        if not isinstance(raw, list):
            raise ValueError(f"{path} must contain a JSON list of goldens")
        goldens.extend(ChessGolden.model_validate(item) for item in raw)

    ids = [g.id for g in goldens]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate golden ids: {sorted(duplicates)}")

    if task is not None:
        goldens = [g for g in goldens if g.task == task]
    return sorted(goldens, key=lambda g: g.id)


DETERMINISTIC_TASKS: tuple[TaskType, ...] = (
    "best_move",
    "deep_line",
    "eval_bucket",
    "endgame",
)
"""The exact-match / line tasks graded without an LLM judge."""


def stratified_sample(
    goldens: list[ChessGolden],
    *,
    per_task: int,
    tasks: tuple[TaskType, ...] = DETERMINISTIC_TASKS,
    seed: int = 0,
) -> list[ChessGolden]:
    """Pick ``per_task`` goldens from each task, deterministically.

    A cheap, representative slice of the suite: every task type is present in equal
    measure so an aggregate score is not dominated by whichever task happens to have
    the most goldens. ``seed`` fixes the choice so a baseline and a treatment run see
    the *same* positions — the only honest way to compare them.
    """
    import random

    rng = random.Random(seed)
    chosen: list[ChessGolden] = []
    for task in tasks:
        pool = sorted((g for g in goldens if g.task == task), key=lambda g: g.id)
        rng.shuffle(pool)
        chosen.extend(pool[:per_task])
    return sorted(chosen, key=lambda g: g.id)


def load_explained_goldens(*, goldens_dir: Path = GOLDENS_DIR) -> list[ChessGolden]:
    """Load position-answer goldens that carry a book explanation."""
    return [
        g
        for g in load_goldens(goldens_dir=goldens_dir)
        if g.task in {"best_move", "eval_bucket", "endgame"} and g.reference_explanation
    ]


def coach_input(golden: ChessGolden) -> CoachInput:
    """Build the question posed to the coach for a golden.

    For teaching and general-chat turns the student's utterance rides in
    ``context``; for mistake diagnosis the candidate move is supplied separately so a
    real coach can call its move-evaluation tool. The deterministic structured tasks
    leave both unset.
    """
    return CoachInput(
        fen=golden.fen,
        task_type=golden.task,
        level=golden.level,
        context=golden.student_message,
        candidate_move=golden.student_move,
        conversation_history=[
            (turn.role, turn.text) for turn in golden.conversation_history
        ],
    )


def _expected_text(golden: ChessGolden) -> str:
    if golden.task == "best_move":
        return " | ".join(golden.solution_moves)
    if golden.task == "eval_bucket":
        return golden.expected_bucket or ""
    if golden.task == "deep_line":
        return " ".join(golden.expected_line)
    if golden.task in {"teaching", "general_chat", "conversation"}:
        return " | ".join(golden.solution_moves) or (golden.expected_bucket or "")
    if golden.task == "mistake_diagnosis":
        return (
            f"student move: {golden.student_move}; best: {golden.engine_best_move}; "
            f"refutation: {golden.engine_refutation}; weaknesses: "
            f"{', '.join(golden.expected_weakness_tags)}"
        )
    if golden.task == "multi_turn_teaching":
        return _multi_turn_reference(golden)
    return f"{golden.expected_result}: {' '.join(golden.solution_moves)}"


def _actual_text(golden: ChessGolden, result: CoachResult) -> str:
    if golden.task == "best_move":
        return result.best_move or ""
    if golden.task == "eval_bucket":
        return result.eval_bucket or ""
    if golden.task == "deep_line":
        return " ".join(result.line or [])
    if golden.task in {
        "mistake_diagnosis",
        "multi_turn_teaching",
        "teaching",
        "general_chat",
        "conversation",
    }:
        return result.explanation or ""
    return f"{result.result}: {result.best_move or ''}"


def to_test_case(golden: ChessGolden, result: CoachResult) -> LLMTestCase:
    """Pair a golden with the coach's answer as a deepeval test case.

    ``input``/``expected_output``/``actual_output`` are human-readable for
    reporting; the metrics read the structured ``golden`` and ``result`` stashed
    in ``metadata``.
    """
    return LLMTestCase(
        input=(golden.student_message or "")
        if golden.task == "general_chat"
        else _conversation_input(golden)
        if golden.task == "conversation"
        else f"[{golden.task}] {golden.fen}",
        actual_output=_actual_text(golden, result) or "<none>",
        expected_output=_expected_text(golden),
        metadata={"golden": golden, "result": result},
    )


def _reference_text(golden: ChessGolden) -> str:
    """The ground truth the judge holds the coach's explanation to.

    Prefers the book's own explanation; always states the engine answer and the
    key ideas so the judge can check both correctness and faithfulness.
    """
    parts = [f"answer: {_expected_text(golden)}"]
    if golden.key_ideas:
        parts.append(f"key ideas: {', '.join(golden.key_ideas)}")
    elif golden.theme:
        parts.append(f"themes: {', '.join(golden.theme)}")
    if golden.reference_explanation:
        parts.append(f"book explanation: {golden.reference_explanation}")
    return "; ".join(parts)


def _general_chat_reference(golden: ChessGolden) -> str:
    """The ground truth for judging a general chess coaching answer."""
    parts = [
        f"level: {golden.level}",
        f"recommended answer: {golden.reference_explanation or ''}",
    ]
    if golden.key_ideas:
        parts.append(f"required key facts: {', '.join(golden.key_ideas)}")
    if golden.theme:
        parts.append(f"topics: {', '.join(golden.theme)}")
    return "; ".join(parts)


def to_judge_case(golden: ChessGolden, result: CoachResult) -> LLMTestCase:
    """Build a test case for the LLM-as-judge over the coach's *explanation*.

    ``actual_output`` is the prose to judge; ``expected_output`` carries the
    book's explanation (when available) plus the engine answer and key ideas the
    coach's explanation must be faithful to.
    """
    actual = result.explanation or "<no explanation>"
    if golden.task == "deep_line":
        actual = f"line: {' '.join(result.line or [])}; explanation: {actual}"
    return LLMTestCase(
        input=f"Position ({golden.task}): {golden.fen}",
        actual_output=actual,
        expected_output=_reference_text(golden),
        metadata={"golden": golden, "result": result},
    )


def _teaching_reference(golden: ChessGolden) -> str:
    """The ground truth for judging a teaching turn — including the spoiler rule."""
    correct = _expected_text(golden)
    parts = [f"correct answer: {correct}"] if correct else []
    if golden.key_ideas:
        parts.append(f"key ideas: {', '.join(golden.key_ideas)}")
    if golden.spoiler_forbidden:
        parts.append(
            "the student asked for a hint, so a good reply GUIDES toward the idea "
            f"and must NOT state the best move ({correct}) outright"
        )
    else:
        parts.append(
            f"the student asked directly, so a good reply STATES the answer "
            f"({correct}) plainly and then explains it"
        )
    if golden.reference_explanation:
        parts.append(f"book explanation: {golden.reference_explanation}")
    return "; ".join(parts)


def to_teaching_case(golden: ChessGolden, result: CoachResult) -> LLMTestCase:
    """Build a judge case for a teaching turn.

    ``input`` is what the student said; ``actual_output`` is the coach's reply;
    ``expected_output`` carries the correct answer, the key ideas, whether the move
    should be withheld or revealed, and the book's explanation.
    """
    return LLMTestCase(
        input=golden.student_message or "",
        actual_output=result.explanation or "<no reply>",
        expected_output=_teaching_reference(golden),
        metadata={"golden": golden, "result": result},
    )


def _mistake_reference(golden: ChessGolden) -> str:
    """Ground truth for judging whether the coach diagnosed a student mistake."""
    parts = [
        f"student move: {golden.student_move}",
        f"engine best move: {golden.engine_best_move}",
        f"engine refutation: {golden.engine_refutation}",
        f"weakness tags: {', '.join(golden.expected_weakness_tags)}",
    ]
    if golden.key_ideas:
        parts.append(f"key ideas: {', '.join(golden.key_ideas)}")
    if golden.reference_explanation:
        parts.append(f"reference explanation: {golden.reference_explanation}")
    return "; ".join(parts)


def to_mistake_case(golden: ChessGolden, result: CoachResult) -> LLMTestCase:
    """Build a judge case for diagnosing a student's played/proposed move."""
    return LLMTestCase(
        input=golden.student_message or "",
        actual_output=result.explanation or "<no diagnosis>",
        expected_output=_mistake_reference(golden),
        metadata={"golden": golden, "result": result},
    )


def _multi_turn_reference(golden: ChessGolden) -> str:
    """Ground truth for a multi-turn teaching transcript."""
    parts: list[str] = []
    correct = _expected_text_for_answer(golden)
    if correct:
        parts.append(f"correct answer: {correct}")
    if golden.expected_reveal_turn is not None:
        parts.append(
            f"first reveal allowed on coach turn: {golden.expected_reveal_turn}"
        )
    if golden.key_ideas:
        parts.append(f"key ideas: {', '.join(golden.key_ideas)}")
    for index, turn in enumerate(golden.conversation, start=1):
        policy = "may reveal" if turn.reveal_allowed else "must not reveal"
        parts.append(
            f"turn {index}: student says {turn.student!r}; coach {policy}; "
            f"expected behavior: {turn.expected_coach_behavior}; "
            f"must include: {', '.join(turn.must_include) or '<none>'}; "
            f"must not include: {', '.join(turn.must_not_include) or '<none>'}"
        )
    if golden.reference_explanation:
        parts.append(f"reference explanation: {golden.reference_explanation}")
    return "; ".join(parts)


def _expected_text_for_answer(golden: ChessGolden) -> str:
    if golden.solution_moves:
        return " | ".join(golden.solution_moves)
    if golden.expected_bucket:
        return golden.expected_bucket
    if golden.expected_result:
        return golden.expected_result
    return golden.engine_best_move or ""


def to_multi_turn_case(golden: ChessGolden, transcript: str) -> LLMTestCase:
    """Build a judge case for a whole multi-turn coaching transcript.

    ``transcript`` should contain the coach's replies in order, ideally labelled by
    turn. The expected output carries the objective reveal policy and final chess
    idea so different coaches can be compared on the same scenario.
    """
    return LLMTestCase(
        input="\n".join(
            f"Student turn {index}: {turn.student}"
            for index, turn in enumerate(golden.conversation, start=1)
        ),
        actual_output=transcript or "<no transcript>",
        expected_output=_multi_turn_reference(golden),
        metadata={"golden": golden, "transcript": transcript},
    )


def to_general_chat_case(golden: ChessGolden, result: CoachResult) -> LLMTestCase:
    """Build a judge case for a non-position chess coaching question."""
    return LLMTestCase(
        input=golden.student_message or "",
        actual_output=result.explanation or "<no reply>",
        expected_output=_general_chat_reference(golden),
        metadata={"golden": golden, "result": result},
    )


def _conversation_input(golden: ChessGolden) -> str:
    """Render the stored dialogue and final student turn for reports/judges."""
    lines: list[str] = []
    if golden.fen:
        lines.append(f"Position (FEN): {golden.fen}")
    if golden.level:
        lines.append(f"Student level: {golden.level}")
    lines.extend(
        f"{turn.role}: {turn.text}" for turn in golden.conversation_history
    )
    lines.append(f"student: {golden.student_message or ''}")
    return "\n".join(lines)


def _conversation_reference(golden: ChessGolden) -> str:
    """Ground truth for a multi-turn conversation eval."""
    parts = [
        f"spoiler policy: {golden.spoiler_policy}",
        f"reference answer: {golden.reference_explanation or ''}",
    ]
    if golden.required_facts:
        parts.append(f"required facts: {', '.join(golden.required_facts)}")
    if golden.key_ideas:
        parts.append(f"key ideas: {', '.join(golden.key_ideas)}")
    if golden.forbidden_claims:
        parts.append(f"forbidden claims: {', '.join(golden.forbidden_claims)}")
    if golden.solution_moves:
        parts.append(
            "moves that may be revealed only if policy allows: "
            f"{' '.join(golden.solution_moves)}"
        )
    return "; ".join(parts)


def to_conversation_case(golden: ChessGolden, result: CoachResult) -> LLMTestCase:
    """Build a judge case for a multi-turn teacher-student conversation."""
    return LLMTestCase(
        input=_conversation_input(golden),
        actual_output=result.explanation or "<no reply>",
        expected_output=_conversation_reference(golden),
        metadata={"golden": golden, "result": result},
    )

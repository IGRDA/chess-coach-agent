"""Codex CLI coach adapter grounded in the same chess tools as the Claude coach.

This module is the provider-specific shell around Codex. It keeps the CLI process,
prompt shape, temporary files and output parsing hidden behind the same small
``answer_sync`` method that the coach-port adapter already consumes. The app
still owns chess truth: Stockfish analysis is computed before Codex is invoked,
embedded in the prompt, and copied back into structured fields after parsing so
provider narration cannot drift from the engine record.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import anyio
import chess

from chess_coach.adapters.coach import tools
from chess_coach.adapters.coach.agent import (
    CoachAgentError,
    CoachAnswer,
    _parse_answer,
    _turn_attrs,
)
from chess_coach.adapters.coach.analysis import (
    MemoizingAnalyzer,
    PositionAnalysis,
    PositionAnalyzer,
    format_score,
)
from chess_coach.adapters.coach.opening_book import OpeningBook
from chess_coach.adapters.coach.prefetch import PositionPrefetcher
from chess_coach.adapters.coach.tablebase import Tablebase
from chess_coach.adapters.observability import tracing

# No app-forced default: when the model is left unset, we omit ``--model`` and let
# the Codex CLI use its own configured default (``~/.codex/config.toml``). Forcing a
# specific id here fought the CLI's config and broke on accounts not entitled to it.
DEFAULT_CODEX_MODEL: str | None = None

# How many plies of the engine's principal variation to surface and to ground a
# deep_line answer with. Curated deep-line goldens run to ~5 plies; a little headroom
# lets a longer forced line still match while extra plies are harmless to the metric.
_PV_PLIES = 8


@dataclass(frozen=True)
class CommandResult:
    """Captured result from a Codex CLI invocation."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], str], CommandResult]

_SYSTEM_PROMPT = (
    "You are a rigorous chess coach. The objective engine facts are already "
    "provided in the prompt. Do not invent chess facts and do not run shell "
    "commands. Use the supplied Stockfish values exactly for structured fields, "
    "then explain the idea clearly at the student's level."
)

_TASK_BRIEF: dict[str, str] = {
    "best_move": "Explain the engine's best move and why it works.",
    "eval_bucket": "Explain who stands better using the engine bucket.",
    "endgame": "Explain the key endgame move and game-theoretic result.",
    "explain": "Answer the student's question about this position.",
    "deep_line": "Calculate and explain a short best-play continuation.",
}

# Prose (judge-graded) turns. These mirror the Claude coach's prompts so the two
# providers are held to the same coaching contract; the engine facts are embedded so
# a concrete claim is never invented.
_TEACH_SYSTEM_PROMPT = (
    "You are a chess coach helping a student in a single coaching turn. The objective "
    "engine facts are provided below. Teach through the reply: if the student asks for "
    "a hint or a nudge, guide toward the idea with a pointer or a question and do NOT "
    "state the best move; if they ask directly, are stuck, or propose a move, answer "
    "plainly and then explain. Never invent concrete facts — use the engine facts for "
    "the best move, the assessment, or an endgame result. Reply in warm, natural prose "
    "(no JSON)."
)
_GENERAL_CHAT_SYSTEM_PROMPT = (
    "You are a rigorous chess coach answering a general chess question, not a board "
    "position. Give accurate, practical instruction in natural prose, pitched to the "
    "student's level. Do not invent book quotations, exact statistics, engine claims, "
    "or rules you are unsure about; if a specific position would be needed, say so and "
    "give the useful general principle."
)
_CONVERSATION_SYSTEM_PROMPT = (
    "You are a chess coach in a multi-turn lesson. Use the prior transcript: remember "
    "the student's goals, misconceptions, earlier hints, and candidate moves already "
    "discussed. If engine facts are provided, use them for any concrete claim; if "
    "none are, answer from general principles and say when a position would be "
    "needed. Reply in natural coaching prose (no JSON)."
)


def _flip_score(analysis: PositionAnalysis) -> str:
    """Render a resulting-position score from the *mover's* point of view.

    ``analysis`` scores the position after the student's move (opponent to move);
    negating it expresses how bad the move is for the student.
    """
    if analysis.mate is not None:
        return format_score(None, -analysis.mate)
    if analysis.cp is not None:
        return format_score(-analysis.cp, None)
    return analysis.score_text()


def _run_codex(command: Sequence[str], stdin: str) -> CommandResult:
    completed = subprocess.run(
        list(command),
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class CodexCoach:
    """One-shot coach backed by ``codex exec`` and grounded by Stockfish first."""

    def __init__(
        self,
        analyzer: PositionAnalyzer,
        book: OpeningBook | None = None,
        *,
        tablebase: Tablebase | None = None,
        model: str | None = DEFAULT_CODEX_MODEL,
        reasoning_effort: str | None = None,
        runner: CommandRunner = _run_codex,
        codex_binary: str = "codex",
    ) -> None:
        self._analyzer = analyzer
        self._book = book or OpeningBook()
        self._tablebase = tablebase or Tablebase()
        self._model = model
        # Reasoning effort trades quality for latency/cost. Left unset it defers to
        # the CLI's own config; the eval loop passes "low" to stay cheap and fast on
        # a ChatGPT-account model (where mini models are unavailable).
        self._reasoning_effort = reasoning_effort
        self._runner = runner
        self._codex_binary = codex_binary

    def answer_sync(
        self,
        fen: str,
        task_type: str,
        level: str | None = None,
        question: str | None = None,
        candidate_move: str | None = None,
    ) -> CoachAnswer:
        """Run Codex once and return a parsed, engine-grounded answer."""
        with tracing.turn_span(
            "coach.answer", _turn_attrs(self._model, fen, task_type, level)
        ) as span:
            span.set_attribute("coach.provider", "codex")
            # Grounding first: Stockfish (and the book/tablebase) run in-process before
            # Codex is invoked, so this child span is the real engine latency.
            with tracing.tool_span(
                "engine.ground_truth",
                {
                    "openinference.span.kind": "TOOL",
                    "tool.name": "stockfish",
                    "chess.fen": fen,
                },
            ):
                analysis = self._analyzer.analyze(fen)
                prompt = self._build_prompt(
                    fen, task_type, level, question, candidate_move, analysis
                )
            # Then the Codex CLI subprocess — its own child span (no native telemetry;
            # that is a Claude Code feature, so we time the process from out here).
            with tracing.tool_span(
                "codex.exec",
                {
                    "openinference.span.kind": "LLM",
                    "llm.model_name": self._model or "codex-default",
                },
            ):
                text = self._run(prompt)
            answer = _parse_answer(text)
            return _ground_answer(answer, task_type, analysis)

    def _run(self, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="chess-coach-codex-") as tmp:
            output_path = Path(tmp) / "answer.md"
            command = [
                self._codex_binary,
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "read-only",
                # `codex exec` is already non-interactive; a read-only sandbox never
                # prompts, and the approval flag was removed in newer Codex CLIs.
                "--output-last-message",
                str(output_path),
            ]
            # Only pin the model when one is explicitly configured; otherwise defer to
            # the Codex CLI's own default so we never request an unentitled model.
            if self._model:
                command += ["--model", self._model]
            # Override reasoning effort when asked (e.g. "low" for a cheap eval loop),
            # via the same `-c key=value` config mechanism the CLI documents.
            if self._reasoning_effort:
                command += ["-c", f"model_reasoning_effort={self._reasoning_effort}"]
            command.append("-")
            result = self._runner(command, prompt)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                raise CoachAgentError(f"codex failed: {detail}")
            if output_path.exists():
                text = output_path.read_text(encoding="utf-8")
                if text.strip():
                    return text
            return result.stdout

    def _build_prompt(
        self,
        fen: str,
        task_type: str,
        level: str | None,
        question: str | None,
        candidate_move: str | None,
        analysis: PositionAnalysis,
    ) -> str:
        truth = _truth_payload(
            self._analyzer,
            self._book,
            self._tablebase,
            fen,
            analysis,
            candidate_move,
        )
        student = f"\nStudent level: {level}" if level else ""
        asks = f"\nStudent question: {question}" if question else ""
        return (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Position FEN: {fen}\n"
            f"Task: {_TASK_BRIEF[task_type]}{student}{asks}\n\n"
            "Engine-grounded facts:\n"
            f"```json\n{json.dumps(truth, indent=2)}\n```\n\n"
            "Reply with a short coaching explanation followed by one fenced JSON "
            "block as the last thing in your message:\n"
            "```json\n"
            '{"best_move": "<uci or null>", "eval_bucket": "<bucket or null>", '
            '"result": "<win|draw|loss or null>", "line": ["<uci>", "..."], '
            '"explanation": "<one or two sentences>"}\n'
            "```\n"
            "Use null for irrelevant fields. Structured scalar values must match "
            "the engine-grounded facts exactly; for deep_line, make the first line "
            "move match the engine best move."
        )


    def _grounded_facts_block(self, fen: str) -> str:
        """The engine/book/tablebase truth for a FEN, as a fenced JSON block."""
        analysis = self._analyzer.analyze(fen)
        truth = _truth_payload(
            self._analyzer, self._book, self._tablebase, fen, analysis, None
        )
        return f"Engine-grounded facts:\n```json\n{json.dumps(truth, indent=2)}\n```\n"

    def teach_sync(self, fen: str, message: str, level: str | None = None) -> str:
        """Answer one live teaching turn as grounded prose (spoiler-aware)."""
        with tracing.turn_span(
            "coach.teach", _turn_attrs(self._model, fen, "explain", level)
        ) as span:
            span.set_attribute("coach.provider", "codex")
            facts = self._grounded_facts_block(fen)
            student = f"\nStudent level: {level}" if level else ""
            prompt = (
                f"{_TEACH_SYSTEM_PROMPT}\n\n"
                f"Position FEN: {fen}{student}\n"
                f'The student says: "{message}"\n\n'
                f"{facts}\n"
                "Respond as their coach."
            )
            return self._run(prompt).strip()

    def general_chat_sync(self, message: str, level: str | None = None) -> str:
        """Answer a non-position chess coaching question as prose."""
        with tracing.turn_span(
            "coach.general_chat", _turn_attrs(self._model, None, "general_chat", level)
        ) as span:
            span.set_attribute("coach.provider", "codex")
            student = f"\nStudent level: {level}" if level else ""
            prompt = (
                f"{_GENERAL_CHAT_SYSTEM_PROMPT}{student}\n"
                f'The student asks: "{message}"\n\n'
                "Respond as their chess coach. Keep it practical, accurate, and clear "
                "enough to turn into training action."
            )
            return self._run(prompt).strip()

    def converse_sync(
        self,
        fen: str | None,
        history: list[tuple[str, str]],
        message: str,
        level: str | None = None,
    ) -> str:
        """Answer the next turn of a supplied multi-turn conversation as prose."""
        with tracing.turn_span(
            "coach.converse", _turn_attrs(self._model, fen or "", "conversation", level)
        ) as span:
            span.set_attribute("coach.provider", "codex")
            facts = self._grounded_facts_block(fen) + "\n" if fen else ""
            position = (
                f"Current position FEN: {fen}\n"
                if fen
                else "No board position given.\n"
            )
            transcript = "\n".join(f"{role}: {text}" for role, text in history)
            if transcript:
                transcript = f"Conversation so far:\n{transcript}\n"
            student = f"\nStudent level: {level}" if level else ""
            prompt = (
                f"{_CONVERSATION_SYSTEM_PROMPT}{student}\n"
                f"{position}{facts}{transcript}"
                f'The student now says: "{message}"\n\n'
                "Respond as their coach, using the conversation history."
            )
            return self._run(prompt).strip()


    def _strong_moves(self, fen: str, n: int = 3) -> list[dict[str, str]]:
        """The engine's top-``n`` moves (MultiPV), when the analyzer supports it.

        This is the correctness guarantee for teaching: every listed move is
        engine-verified sound, so a coach that teaches one of them can never teach a
        bad move — while still being free to pick the most *instructive* one instead
        of the engine's single arbitrary #1. Empty when the analyzer has no MultiPV.
        """
        top = getattr(self._analyzer, "top_moves", None)
        if top is None:
            return []
        try:
            return [{"san": m.san, "score": m.score} for m in top(fen, n)]
        except (ValueError, RuntimeError):
            return []

    def _light_facts_block(
        self, fen: str, candidate: str | None = None
    ) -> str:
        """Grounding for teaching that keeps the coach *correct* without forcing the
        engine's single move.

        The failure of embedding one best move is over-steer: when several moves are
        equally optimal, the model parrots the engine's arbitrary pick over the
        pedagogically-curated one. But hiding the move entirely risks the coach
        teaching an unsound move. The fix is MultiPV: give the *set* of top moves
        (all engine-verified strong) plus the assessment, so the taught move is both
        correct and free to be the instructive one.
        """
        analysis = self._analyzer.analyze(fen)
        facts: dict[str, object] = {
            "score": analysis.score_text(),
            "eval_bucket": analysis.bucket,
            "result": analysis.result,
            "engine_verified_strong_moves": self._strong_moves(fen),
            "features": _safe_features(fen),
            "opening": _safe_opening(self._book, fen),
            "tablebase": _safe_tablebase(self._tablebase, fen),
        }
        if candidate:
            facts["student_move"] = _safe_candidate(self._analyzer, fen, candidate)
        return (
            "Reference facts (teach one of the engine-verified strong moves):\n"
            f"```json\n{json.dumps(facts, indent=2)}\n```\n"
        )

    def teach_light_sync(
        self, fen: str, message: str, level: str | None = None
    ) -> str:
        """Teaching turn grounded on the *set* of engine-best moves (MultiPV).

        Correct by construction — any move it teaches is one the engine verified as
        strong — while free to choose the most instructive of them rather than the
        engine's single #1, which is what over-steered the reply before.
        """
        with tracing.turn_span(
            "coach.teach", _turn_attrs(self._model, fen, "explain", level)
        ) as span:
            span.set_attribute("coach.provider", "codex")
            facts = self._light_facts_block(fen)
            student = f"\nStudent level: {level}" if level else ""
            prompt = (
                f"{_TEACH_SYSTEM_PROMPT}\n\n"
                f"Position FEN: {fen}{student}\n"
                f'The student says: "{message}"\n\n'
                f"{facts}\n"
                "Respond as their coach. Teach one of the engine-verified strong moves "
                "above — pick the most instructive one for this student; never name a "
                "move that is not among them."
            )
            return self._run(prompt).strip()

    def _refutation(self, fen: str, student_move: str | None) -> dict[str, object]:
        """What punishes the student's move: the engine's best reply and the resulting
        evaluation from the student's point of view. Empty if there is no legal move to
        test — this grounds *why* a move is worse, which the diagnosis judge rewards."""
        if not student_move:
            return {}
        board = chess.Board(fen)
        try:
            parsed = tools._parse_move(board, student_move)
        except ValueError:
            return {}
        board.push(parsed)
        if board.is_game_over():
            return {"note": "the move ends the game (mate/stalemate)"}
        reply = self._analyzer.analyze(board.fen())
        return {
            "best_reply_san": reply.best_move_san,
            "reply_line_uci": list(reply.pv_uci[:6]),
            "eval_after_from_student_pov": _flip_score(reply),
        }

    def diagnose_light_sync(
        self,
        fen: str,
        student_move: str | None,
        message: str,
        level: str | None = None,
    ) -> str:
        """Diagnose a student's move with full engine grounding.

        A diagnosis is *rewarded* for naming the engine's stronger move and the
        concrete refutation and *penalized* for hedging ("your move is fine") or
        omitting/contradicting the engine. Keep the best move/line and add the
        punishing reply, then ask for a candid verdict/reason/habit.

        (A lean "why-first" variant was tried via a skill-creator A/B but did not
        repeatably beat this on a second run — the difference was within judge noise,
        so this structured version stands.)
        """
        with tracing.turn_span(
            "coach.teach", _turn_attrs(self._model, fen, "explain", level)
        ) as span:
            span.set_attribute("coach.provider", "codex")
            facts = self._grounded_facts_block(fen)
            refutation = self._refutation(fen, student_move)
            ref_block = (
                "How the student's move is answered (engine):\n"
                f"```json\n{json.dumps(refutation, indent=2)}\n```\n"
                if refutation
                else ""
            )
            student = f"\nStudent level: {level}" if level else ""
            asks = f'\nThe student asks: "{message}"' if message else ""
            move = (
                f"\nThe student played/proposed: {student_move}"
                if student_move
                else ""
            )
            prompt = (
                f"{_TEACH_SYSTEM_PROMPT}\n\n"
                f"Position FEN: {fen}{student}{move}{asks}\n\n"
                f"{facts}\n{ref_block}\n"
                "Diagnose the student's move against the engine's best. Structure it: "
                "(1) verdict — state plainly that a stronger move existed and name the "
                "engine's best move (do not soften a clear improvement as 'fine'); "
                "(2) reason — the concrete tactic, weakness, or line that makes the "
                "student's move worse (use the punishing reply above); (3) habit — the "
                "reusable rule to carry to similar positions, and name the standard "
                "method, mating pattern, or endgame technique by its established name "
                "when one applies. Pitch it to their level."
            )
            return self._run(prompt).strip()


class CodexChatSession:
    """A minimal chat-compatible Codex session.

    Codex CLI is invoked once per turn, so this is not a persistent conversation
    like the Claude SDK client. It still satisfies the chat port and keeps the
    board grounded by passing the current FEN each time.
    """

    def __init__(
        self,
        analyzer: PositionAnalyzer,
        book: OpeningBook | None = None,
        *,
        tablebase: Tablebase | None = None,
        model: str | None = DEFAULT_CODEX_MODEL,
        runner: CommandRunner = _run_codex,
    ) -> None:
        # Memoized so the prefetcher has somewhere to leave its warm result, and so a
        # turn that analyses the same FEN twice only searches once.
        self._analyzer = (
            analyzer
            if isinstance(analyzer, MemoizingAnalyzer)
            else MemoizingAnalyzer(analyzer)
        )
        self._prefetcher = PositionPrefetcher(self._analyzer)
        self._coach = CodexCoach(
            self._analyzer,
            book,
            tablebase=tablebase,
            model=model,
            runner=runner,
        )

    async def __aenter__(self) -> CodexChatSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._prefetcher.close()
        return None

    def prefetch(self, fen: str) -> None:
        """Warm the engine for ``fen`` in the background; returns immediately."""
        self._prefetcher.schedule(fen)

    async def stream(
        self, fen: str, message: str, level: str | None = None
    ) -> AsyncIterator[str]:
        answer = await anyio.to_thread.run_sync(
            self._coach.answer_sync, fen, "explain", level, message, None
        )
        if answer.explanation:
            yield answer.explanation

    def assess(self, fen: str) -> str:
        """The engine's assessment bucket for a position."""
        return self._analyzer.analyze(fen).bucket


def _truth_payload(
    analyzer: PositionAnalyzer,
    book: OpeningBook,
    tablebase: Tablebase,
    fen: str,
    analysis: PositionAnalysis,
    candidate_move: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "best_move_uci": analysis.best_move_uci,
        "best_move_san": analysis.best_move_san,
        "score": analysis.score_text(),
        "eval_bucket": analysis.bucket,
        "result": analysis.result,
        # The engine's principal variation — its best line for both sides. This is
        # the calculated continuation the coach narrates for a deep_line task,
        # instead of guessing moves ply by ply.
        "best_line_uci": list(analysis.pv_uci[:_PV_PLIES]),
        "best_line_san": list(analysis.pv_san[:_PV_PLIES]),
        "features": _safe_features(fen),
        "opening": _safe_opening(book, fen),
        "tablebase": _safe_tablebase(tablebase, fen),
    }
    if candidate_move:
        payload["candidate_move"] = _safe_candidate(analyzer, fen, candidate_move)
    return payload


def _safe_features(fen: str) -> object:
    try:
        f = tools.position_features(fen)
    except ValueError as exc:
        return {"error": str(exc)}
    return {
        "side_to_move": f.side_to_move,
        "in_check": f.in_check,
        "checks": f.checks,
        "captures": f.captures,
        "targets": f.hanging_targets,
        "weaknesses": f.hanging_own,
        "material": f.material,
        "castling": f.castling,
    }


def _safe_opening(book: OpeningBook, fen: str) -> object:
    try:
        info = book.lookup(fen)
    except ValueError as exc:
        return {"error": str(exc)}
    if not info.is_known() and not info.book_moves:
        return "out of book"
    return {
        "name": info.name or "unnamed",
        "eco": info.eco,
        "book_moves": [m.san for m in info.book_moves],
    }


def _safe_tablebase(tablebase: Tablebase, fen: str) -> object:
    try:
        result = tablebase.probe(fen)
    except ValueError as exc:
        return {"error": str(exc)}
    if not result.available:
        return "tablebase unavailable"
    return {
        "result": result.wdl,
        "dtz": result.dtz,
        "best_moves": list(result.best_moves),
    }


def _safe_candidate(
    analyzer: PositionAnalyzer, fen: str, candidate_move: str
) -> object:
    try:
        result = tools.evaluate_move(analyzer, fen, candidate_move)
    except (ValueError, RuntimeError) as exc:
        return {"move": candidate_move, "error": str(exc)}
    return {
        "move": result.move_san,
        "uci": result.move_uci,
        "verdict": result.verdict,
        "cp_loss": result.cp_loss,
        "score": result.score_text,
        "is_best": result.is_best,
    }


def _ground_answer(
    answer: CoachAnswer, task_type: str, analysis: PositionAnalysis
) -> CoachAnswer:
    best_move = answer.best_move
    eval_bucket = answer.eval_bucket
    result = answer.result
    line = answer.line
    if task_type in {"best_move", "endgame"}:
        best_move = analysis.best_move_uci
    if task_type == "deep_line":
        best_move = analysis.best_move_uci
        # Ground the whole continuation in the engine's principal variation, not the
        # model's guesses: the first move is the engine best move by construction, and
        # the reply/continuation are the engine's own line. Falls back to the model's
        # line only if the engine somehow returned no PV.
        engine_line = list(analysis.pv_uci[:_PV_PLIES])
        line = engine_line or (
            [analysis.best_move_uci, *line[1:]] if line else [analysis.best_move_uci]
        )
    if task_type == "eval_bucket":
        eval_bucket = analysis.bucket
    if task_type == "endgame":
        result = analysis.result
    return CoachAnswer(
        best_move=best_move,
        eval_bucket=eval_bucket,
        result=result,
        line=line,
        explanation=answer.explanation,
        raw=answer.raw,
    )

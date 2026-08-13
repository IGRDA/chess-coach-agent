"""The real coach under evaluation: the Claude agent, wired to the harness.

This is what ``COACH_TASK=agent`` selects. It satisfies the same
:class:`~evals.harness.task.CoachTask` contract the reference oracle does, but the
answer comes from the actual :class:`~chess_coach.adapters.coach.agent.AgentCoach`
— a Claude agent that consults tools and narrates.

Two deliberate choices keep the evaluation honest and affordable:

- **One source of truth.** The agent's ``analyze_position`` tool is backed by the
  *same* pinned :class:`~evals.harness.engine.StockfishOracle` that authored the
  goldens (via :class:`OracleAnalyzer`). So when the agent grounds an answer in the
  engine, it is grounding it in exactly the yardstick it is graded against — the
  structured metrics measure whether the agent *correctly orchestrates and reports*
  that truth (and, under ``-m judge``, whether its prose is faithful), not whether
  two near-identical engine configs happen to agree.
- **A versioned cache.** Every answer is memoised on disk, keyed by the position
  *and* a fingerprint of the skill, prompt and model. Re-running the suite is then
  instant, and changing the skill busts the cache automatically — so iteration is
  cheap but never stale. Set ``AGENT_CACHE=0`` to bypass it.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

import chess

from chess_coach.adapters.coach import agent as agent_mod
from chess_coach.adapters.coach.agent import AgentCoach, CoachAnswer
from chess_coach.adapters.coach.analysis import PositionAnalysis
from chess_coach.adapters.coach.opening_book import OpeningBook
from chess_coach.adapters.coach.skills import fingerprint_text
from evals.harness.engine import StockfishOracle
from evals.harness.task import CoachInput, CoachResult

_CACHE_PATH = Path(__file__).resolve().parents[1] / "results" / "agent_cache.json"
CacheEntry = dict[str, str | list[str] | None]


def _skills_text() -> str:
    """The concatenated text of every skill file — so editing any skill busts cache."""
    return fingerprint_text()


def _pv_san(board: chess.Board, pv_uci: tuple[str, ...]) -> tuple[str, ...]:
    """Render a UCI principal variation to SAN on a throwaway copy of the board."""
    walker = board.copy(stack=False)
    san: list[str] = []
    for uci in pv_uci:
        move = chess.Move.from_uci(uci)
        san.append(walker.san(move))
        walker.push(move)
    return tuple(san)


class OracleAnalyzer:
    """Adapt the harness :class:`StockfishOracle` to the agent's analyzer port.

    The oracle is the dataset's own engine; reusing it as the agent's tool means
    the agent reads ground truth from the very source the goldens were built with.
    """

    def __init__(self, oracle: StockfishOracle) -> None:
        self._oracle = oracle

    def analyze(self, fen: str) -> PositionAnalysis:
        a = self._oracle.assess(fen)
        board = chess.Board(fen)
        san = board.san(chess.Move.from_uci(a.best_move_uci))
        pv_san = _pv_san(board, a.pv_uci)
        return PositionAnalysis(
            best_move_uci=a.best_move_uci,
            best_move_san=san,
            cp=a.cp,
            mate=a.mate,
            bucket=a.bucket,
            result=a.result(),  # type: ignore[arg-type]
            pv_uci=a.pv_uci,
            pv_san=pv_san,
        )


def _fingerprint(model: str) -> str:
    """A short hash of everything that should invalidate cached answers."""
    parts = [model, agent_mod._SYSTEM_PROMPT, agent_mod._build_prompt.__doc__ or ""]
    parts.append(_skills_text())
    # The prompt templates matter; capture them via representative renders. Include the
    # teaching path (system + prompt) so a change there busts cached teaching answers.
    parts.append(agent_mod._build_prompt("<fen>", "best_move", "beginner"))
    parts.append(agent_mod._build_prompt("<fen>", "deep_line", "advanced"))
    parts.append(agent_mod._TEACH_SYSTEM_PROMPT)
    parts.append(agent_mod._build_teach_prompt("<fen>", "<msg>", "beginner"))
    parts.append(agent_mod._GENERAL_CHAT_SYSTEM_PROMPT)
    parts.append(agent_mod._build_general_chat_prompt("<msg>", "beginner"))
    parts.append(agent_mod._CONVERSATION_SYSTEM_PROMPT)
    parts.append(
        agent_mod._build_conversation_prompt(
            "<fen>", [("student", "<old>"), ("coach", "<reply>")], "<msg>", "beginner"
        )
    )
    digest = hashlib.sha256("\x00".join(parts).encode()).hexdigest()
    return digest[:12]


class AgentTask:
    """``CoachTask`` backed by the real Claude agent, with a versioned disk cache."""

    def __init__(
        self,
        oracle: StockfishOracle,
        *,
        model: str | None = None,
        use_cache: bool | None = None,
    ) -> None:
        self._model = model or os.environ.get(
            "CHESS_COACH_MODEL", agent_mod.DEFAULT_MODEL
        )
        self._coach = AgentCoach(
            OracleAnalyzer(oracle), OpeningBook(), model=self._model
        )
        self._fp = _fingerprint(self._model)
        if use_cache is None:
            use_cache = os.environ.get("AGENT_CACHE", "1") != "0"
        self._use_cache = use_cache
        self._cache = _load_cache() if use_cache else {}

    def _key(self, task_input: CoachInput) -> str:
        return cache_key(
            self._fp,
            task_input.task_type,
            task_input.level,
            task_input.fen,
            task_input.context,
            task_input.candidate_move,
            task_input.conversation_history,
        )

    def __call__(self, task_input: CoachInput) -> CoachResult:
        key = self._key(task_input)
        if self._use_cache and key in self._cache:
            answer = _answer_from_cache(self._cache[key])
        else:
            answer = answer_for_input(self._coach, task_input)
            if self._use_cache:
                self._cache[key] = {
                    "best_move": answer.best_move,
                    "eval_bucket": answer.eval_bucket,
                    "result": answer.result,
                    "line": answer.line,
                    "explanation": answer.explanation,
                    "raw": "",  # keep the cache lean; the raw transcript isn't graded
                }
                _save_cache(self._cache)
        return CoachResult(
            best_move=answer.best_move,
            eval_bucket=answer.eval_bucket,
            result=answer.result,  # type: ignore[arg-type]
            line=answer.line,
            explanation=answer.explanation,
        )


class SyncCoach(Protocol):
    """The blocking coaching surface this runner drives.

    ``AgentCoach`` and ``CodexCoach`` are unrelated classes that expose the same
    four synchronous entry points, and the runners accept either. The contract is
    therefore structural, not an inheritance relationship.
    """

    def answer_sync(
        self,
        fen: str,
        task_type: str,
        level: str | None = None,
        question: str | None = None,
        candidate_move: str | None = None,
    ) -> CoachAnswer: ...

    def teach_sync(self, fen: str, message: str, level: str | None = None) -> str: ...

    def general_chat_sync(self, message: str, level: str | None = None) -> str: ...

    def converse_sync(
        self,
        fen: str | None,
        history: list[tuple[str, str]],
        message: str,
        level: str | None = None,
    ) -> str: ...


def answer_for_input(coach: SyncCoach, ci: CoachInput) -> CoachAnswer:
    """Run one task input through the agent (blocking).

    A teaching turn is a live coaching reply — prose only, through the interactive
    skill so it respects spoiler control. Mistake diagnosis reuses the explanatory
    path with the student's candidate move supplied to the move-evaluation tool.
    """
    if ci.task_type == "teaching":
        if ci.fen is None:
            raise ValueError("teaching task requires a FEN")
        prose = coach.teach_sync(ci.fen, ci.context or "", ci.level)
        return CoachAnswer(explanation=prose)
    if ci.task_type == "general_chat":
        prose = coach.general_chat_sync(ci.context or "", ci.level)
        return CoachAnswer(explanation=prose)
    if ci.task_type == "conversation":
        prose = coach.converse_sync(
            ci.fen, ci.conversation_history, ci.context or "", ci.level
        )
        return CoachAnswer(explanation=prose)
    if ci.task_type == "multi_turn_teaching":
        raise NotImplementedError("multi-turn teaching needs a transcript runner")
    if ci.fen is None:
        raise ValueError(f"{ci.task_type} task requires a FEN")
    if ci.task_type == "mistake_diagnosis":
        return coach.answer_sync(
            ci.fen,
            "explain",
            ci.level,
            question=ci.context,
            candidate_move=ci.candidate_move,
        )
    return coach.answer_sync(ci.fen, ci.task_type, ci.level, question=ci.context)


async def aanswer_for_input(coach: AgentCoach, ci: CoachInput) -> CoachAnswer:
    """Run one task input through the agent (async, for the concurrent runner)."""
    if ci.task_type == "teaching":
        if ci.fen is None:
            raise ValueError("teaching task requires a FEN")
        prose = await coach.teach(ci.fen, ci.context or "", ci.level)
        return CoachAnswer(explanation=prose)
    if ci.task_type == "general_chat":
        prose = await coach.general_chat(ci.context or "", ci.level)
        return CoachAnswer(explanation=prose)
    if ci.task_type == "conversation":
        prose = await coach.converse(
            ci.fen, ci.conversation_history, ci.context or "", ci.level
        )
        return CoachAnswer(explanation=prose)
    if ci.task_type == "multi_turn_teaching":
        raise NotImplementedError("multi-turn teaching needs a transcript runner")
    if ci.fen is None:
        raise ValueError(f"{ci.task_type} task requires a FEN")
    if ci.task_type == "mistake_diagnosis":
        return await coach.answer(
            ci.fen,
            "explain",
            ci.level,
            question=ci.context,
            candidate_move=ci.candidate_move,
        )
    return await coach.answer(ci.fen, ci.task_type, ci.level, question=ci.context)


def cache_key(
    fp: str,
    task_type: str,
    level: str | None,
    fen: str | None,
    context: str | None = None,
    candidate_move: str | None = None,
    history: list[tuple[str, str]] | None = None,
) -> str:
    """The disk-cache key for one answer: position fields under a version fingerprint.

    Defined here once so the pytest task and the concurrent runner agree byte-for-
    byte on where an answer lives. ``context`` (the student's utterance) and
    ``candidate_move`` are part of the key so two teaching or diagnosis turns on the
    same position don't collide.
    """
    raw = f"{fp}|{task_type}|{level}|{fen}|{context}|{candidate_move}|{history or []}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _answer_from_cache(entry: CacheEntry) -> CoachAnswer:
    """Rebuild a :class:`CoachAnswer` from a cache entry (typed, not unpacked)."""
    raw_line = entry.get("line")
    line = raw_line if isinstance(raw_line, list) else None
    return CoachAnswer(
        best_move=_cache_str(entry.get("best_move")),
        eval_bucket=_cache_str(entry.get("eval_bucket")),
        result=_cache_str(entry.get("result")),
        line=line,
        explanation=_cache_str(entry.get("explanation")) or "",
    )


def _cache_str(value: str | list[str] | None) -> str | None:
    return value if isinstance(value, str) else None


def _load_cache() -> dict[str, CacheEntry]:
    try:
        data = json.loads(_CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict[str, CacheEntry]) -> None:
    _CACHE_PATH.parent.mkdir(exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2) + "\n")

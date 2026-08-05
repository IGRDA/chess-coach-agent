"""The coaching agent: a Claude agent grounded in Stockfish and opening theory.

This is the "brain" the whole product is organised around. Given a position and
what is being asked (the best move, an assessment, or an endgame verdict), it runs
a Claude agent that is *equipped* — not left to guess — with two in-process tools:
``analyze_position`` (engine ground truth) and ``opening_lookup`` (book theory).
The agent decides which to consult, reads the objective facts, and returns a
structured answer plus a coach's explanation.

Deep module: the interface is one call, :meth:`AgentCoach.answer`. Hidden inside
are the Claude Agent SDK wiring, the in-process MCP tool server, a deliberately
tight tool allowlist (the agent may touch *only* the two chess tools — no shell,
no web, no filesystem), skill loading, model selection, and the parsing of the
model's final JSON back into a typed answer.

Why the tools return the truth the answer is graded on: a coach that invents an
evaluation is worse than useless. Grounding every structured field in Stockfish is
the design, not a shortcut — the agent's own contribution is choosing the right
tool, naming the opening when relevant, and explaining the position faithfully.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from chess_coach.adapters.coach import tools
from chess_coach.adapters.coach.analysis import MemoizingAnalyzer, PositionAnalyzer
from chess_coach.adapters.coach.opening_book import OpeningBook
from chess_coach.adapters.coach.tablebase import Tablebase
from chess_coach.adapters.observability import tracing

TaskType = Literal["best_move", "eval_bucket", "endgame", "explain", "deep_line"]

# Default coaching model. Structured answers are engine-grounded, so this choice
# governs tool-use reliability and explanation quality rather than chess strength.
DEFAULT_MODEL = "claude-sonnet-4-5"

# The skill library. Each skill declares its own least-authority tool subset in its
# frontmatter; the model loads the one that fits the task (progressive disclosure).
DEFAULT_SKILLS = [
    "tactics-coach",
    "assessment-coach",
    "endgame-coach",
    "interactive-coach",
]

# How many plies of the engine's principal variation to surface to the agent. Enough
# for a deep continuation without flooding the tool result with a 20-ply line.
_PV_PLIES = 8

_MCP_SERVER = "chess"
_ANALYZE = f"mcp__{_MCP_SERVER}__analyze_position"
_OPENING = f"mcp__{_MCP_SERVER}__opening_lookup"
_FEATURES = f"mcp__{_MCP_SERVER}__position_features"
_LEGAL = f"mcp__{_MCP_SERVER}__legal_moves"
_EVALUATE = f"mcp__{_MCP_SERVER}__evaluate_move"
_COMPARE = f"mcp__{_MCP_SERVER}__compare_candidates"
_TABLEBASE = f"mcp__{_MCP_SERVER}__probe_tablebase"
_ALL_TOOLS = [
    _ANALYZE,
    _OPENING,
    _FEATURES,
    _LEGAL,
    _EVALUATE,
    _COMPARE,
    _TABLEBASE,
]


@dataclass(frozen=True)
class CoachAnswer:
    """The agent's structured answer plus its narration."""

    best_move: str | None = None
    eval_bucket: str | None = None
    result: str | None = None
    line: list[str] | None = None
    explanation: str = ""
    raw: str = ""


class CoachAgentError(RuntimeError):
    """Raised when the agent produces no parseable structured answer."""


def _text(payload: str) -> dict[str, Any]:
    """Wrap a tool's string result in the SDK's content envelope."""
    return {"content": [{"type": "text", "text": payload}]}


def _turn_attrs(
    model: str | None, fen: str | None, task_type: str, level: str | None
) -> dict[str, Any]:
    """Span attributes describing one coaching turn (OpenInference-friendly keys).

    ``model`` may be ``None`` for Codex (it defers to the CLI's own default); the
    attribute is simply dropped in that case.
    """
    attrs: dict[str, Any] = {
        "openinference.span.kind": "AGENT",
        "llm.model_name": model,
        "coach.task_type": task_type,
        "coach.level": level,
    }
    if fen is not None:
        attrs["chess.fen"] = fen
    return attrs


def _as_moves(value: Any) -> list[str]:
    """Accept a candidate-move list as a JSON array or a delimited string."""
    if isinstance(value, list):
        return [str(m).strip() for m in value if str(m).strip()]
    if isinstance(value, str):
        return [m for m in re.split(r"[,\s]+", value.strip()) if m]
    return []


def _chess_tools(
    analyzer: PositionAnalyzer, book: OpeningBook, tablebase: Tablebase
) -> Any:
    """Build the in-process MCP server exposing the chess kernel to the agent.

    Tools return records, not prose. The blocking engine calls are pushed onto a
    worker thread so the async agent loop (chat, eval) never stalls the caller's
    event loop while Stockfish thinks.
    """

    @tool(
        "analyze_position",
        "Get Stockfish ground truth for a position given as FEN: the best move "
        "(UCI and SAN), the score, the assessment bucket (losing/worse/equal/"
        "better/winning), the win/draw/loss result, and the engine's principal "
        "variation — its best line for both sides (UCI and SAN) — all from the side "
        "to move. Use `line_uci` directly when asked for a continuation; do not "
        "reconstruct it move by move.",
        {"fen": str},
    )
    @tracing.trace_tool("analyze_position")
    async def analyze_position(args: dict[str, Any]) -> dict[str, Any]:
        try:
            a = await anyio.to_thread.run_sync(analyzer.analyze, args["fen"])
        except (ValueError, RuntimeError) as exc:
            return _text(f"error: {exc}")
        return _text(
            json.dumps(
                {
                    "best_move_uci": a.best_move_uci,
                    "best_move_san": a.best_move_san,
                    "score": a.score_text(),
                    "eval_bucket": a.bucket,
                    "result": a.result,
                    "line_uci": list(a.pv_uci[:_PV_PLIES]),
                    "line_san": list(a.pv_san[:_PV_PLIES]),
                }
            )
        )

    @tool(
        "opening_lookup",
        "Look a FEN up in the opening book. Returns the opening name and ECO code "
        "if the position is known theory, plus the book moves played from it. "
        "Use it in the opening; it reports 'out of book' otherwise.",
        {"fen": str},
    )
    @tracing.trace_tool("opening_lookup")
    async def opening_lookup(args: dict[str, Any]) -> dict[str, Any]:
        try:
            info = book.lookup(args["fen"])
        except ValueError as exc:
            return _text(f"error: {exc}")
        if not info.is_known() and not info.book_moves:
            return _text("out of book")
        return _text(
            json.dumps(
                {
                    "opening": info.name or "unnamed",
                    "eco": info.eco,
                    "book_moves": [m.san for m in info.book_moves],
                }
            )
        )

    @tool(
        "position_features",
        "A quick-sight scan of a FEN (no engine): the legal checks and captures, and "
        "the loose pieces on each side — enemy pieces you can win ('targets') and "
        "your own pieces under threat ('weaknesses'), plus material and side to move.",
        {"fen": str},
    )
    @tracing.trace_tool("position_features")
    async def position_features(args: dict[str, Any]) -> dict[str, Any]:
        try:
            f = tools.position_features(args["fen"])
        except ValueError as exc:
            return _text(f"error: {exc}")
        return _text(
            json.dumps(
                {
                    "side_to_move": f.side_to_move,
                    "in_check": f.in_check,
                    "checks": f.checks,
                    "captures": f.captures,
                    "targets": f.hanging_targets,
                    "weaknesses": f.hanging_own,
                    "material": f.material,
                    "castling": f.castling,
                }
            )
        )

    @tool(
        "legal_moves",
        "List the legal moves in a position given as FEN (UCI and SAN), each flagged "
        "as check/capture. Pass only_checks=true for just the checking moves. Use it "
        "to build a candidate list or to verify a move you are about to name is legal.",
        {"fen": str, "only_checks": bool},
    )
    @tracing.trace_tool("legal_moves")
    async def legal_moves(args: dict[str, Any]) -> dict[str, Any]:
        try:
            moves = tools.legal_moves(
                args["fen"], only_checks=bool(args.get("only_checks"))
            )
        except ValueError as exc:
            return _text(f"error: {exc}")
        return _text(
            json.dumps(
                [
                    {
                        "san": m.san,
                        "uci": m.uci,
                        "is_check": m.is_check,
                        "is_capture": m.is_capture,
                    }
                    for m in moves
                ]
            )
        )

    @tool(
        "evaluate_move",
        "Score one specific move (UCI or SAN) in a FEN: how much it gives up versus "
        "the engine's best (centipawn loss), a verdict (best/good/inaccuracy/mistake/"
        "blunder), and the evaluation it reaches. Use it to judge a move the student "
        "is considering.",
        {"fen": str, "move": str},
    )
    @tracing.trace_tool("evaluate_move")
    async def evaluate_move(args: dict[str, Any]) -> dict[str, Any]:
        try:
            e = await anyio.to_thread.run_sync(
                tools.evaluate_move, analyzer, args["fen"], args["move"]
            )
        except (ValueError, RuntimeError) as exc:
            return _text(f"error: {exc}")
        return _text(
            json.dumps(
                {
                    "move": e.move_san,
                    "uci": e.move_uci,
                    "verdict": e.verdict,
                    "cp_loss": e.cp_loss,
                    "score": e.score_text,
                    "is_best": e.is_best,
                }
            )
        )

    @tool(
        "compare_candidates",
        "Rank a shortlist of candidate moves (UCI or SAN) best-first by the engine's "
        "evaluation, each with its centipawn loss and verdict. Pass the moves you or "
        "the student want to compare.",
        {"fen": str, "moves": list},
    )
    @tracing.trace_tool("compare_candidates")
    async def compare_candidates(args: dict[str, Any]) -> dict[str, Any]:
        moves = _as_moves(args.get("moves"))
        try:
            ranked = await anyio.to_thread.run_sync(
                tools.compare_candidates, analyzer, args["fen"], moves
            )
        except (ValueError, RuntimeError) as exc:
            return _text(f"error: {exc}")
        return _text(
            json.dumps(
                [
                    {
                        "move": e.move_san,
                        "uci": e.move_uci,
                        "verdict": e.verdict,
                        "cp_loss": e.cp_loss,
                        "score": e.score_text,
                        "is_best": e.is_best,
                    }
                    for e in ranked
                ]
            )
        )

    @tool(
        "probe_tablebase",
        "For endgames of seven pieces or fewer, get the exact win/draw/loss and the "
        "distance-to-zeroing from a Syzygy tablebase, plus the moves that keep the "
        "result. Reports 'tablebase unavailable' when none is configured or there are "
        "too many pieces.",
        {"fen": str},
    )
    @tracing.trace_tool("probe_tablebase")
    async def probe_tablebase(args: dict[str, Any]) -> dict[str, Any]:
        try:
            r = await anyio.to_thread.run_sync(tablebase.probe, args["fen"])
        except ValueError as exc:
            return _text(f"error: {exc}")
        if not r.available:
            return _text("tablebase unavailable")
        return _text(
            json.dumps(
                {"result": r.wdl, "dtz": r.dtz, "best_moves": list(r.best_moves)}
            )
        )

    return create_sdk_mcp_server(
        name=_MCP_SERVER,
        tools=[
            analyze_position,
            opening_lookup,
            position_features,
            legal_moves,
            evaluate_move,
            compare_candidates,
            probe_tablebase,
        ],
    )


_TASK_BRIEF: dict[str, str] = {
    "best_move": (
        "Find the single best move. Report it in the `best_move` field as a UCI "
        "string (e.g. e1e8, c7c8n for underpromotion)."
    ),
    "eval_bucket": (
        "Assess who stands better. Report the `eval_bucket` field as exactly one "
        "of: losing, worse, equal, better, winning (from the side to move)."
    ),
    "endgame": (
        "This is an endgame technique problem. Report the key move in `best_move` "
        "(UCI) and the game-theoretic outcome in `result` as one of: win, draw, "
        "loss (from the side to move)."
    ),
    "deep_line": (
        "Calculate a short best-play continuation, not only the first move. Take the "
        "continuation from analyze_position's `line_uci` (the engine's principal "
        "variation for both sides) rather than guessing moves. Report the first move "
        "in `best_move` and report `line` as a JSON array of UCI moves in order, "
        "alternating both sides."
    ),
    "explain": (
        "Answer the student's question about this position in plain language. "
        "Ground yourself in analyze_position first, then teach. Fill `best_move` "
        "and/or `eval_bucket` only if they help the answer; `explanation` carries "
        "the substance."
    ),
}

_SYSTEM_PROMPT = (
    "You are a rigorous chess coach. You never guess concrete facts about a "
    "position — you verify them with your tools. For any position you are given, "
    "call analyze_position to get Stockfish's best move, score, assessment bucket "
    "and result, and use those values verbatim in your structured answer. Reach for "
    "your other tools when they help you teach: position_features to see the checks, "
    "captures and loose pieces at a glance; compare_candidates and evaluate_move to "
    "weigh moves the student is considering; opening_lookup to name an opening; "
    "probe_tablebase for exact endgame truth. Then teach: explain *why* the move or "
    "assessment is right in plain, encouraging language pitched to the student's "
    "level. Your loaded skill guides how."
)


def _build_prompt(
    fen: str,
    task_type: str,
    level: str | None,
    question: str | None = None,
    candidate_move: str | None = None,
) -> str:
    brief = _TASK_BRIEF[task_type]
    lvl = f" The student is a {level} player." if level else ""
    asks = ""
    if question:
        asks += f'\nThe student asks: "{question}" Answer it directly.'
    if candidate_move:
        asks += (
            f"\nThe student is considering the move {candidate_move}. Compare it "
            "against the engine's best move from analyze_position and explain "
            "candidly whether it is a good idea, what it overlooks, or why it works."
        )
    return (
        f"Position (FEN): {fen}\n"
        f"Task: {brief}{lvl}{asks}\n\n"
        "First call analyze_position on this exact FEN (and opening_lookup if it "
        "looks like an opening). Then reply with your coaching explanation followed "
        "by a single fenced JSON code block as the LAST thing in your message, of "
        "the form:\n"
        "```json\n"
        '{"best_move": "<uci or null>", "eval_bucket": "<bucket or null>", '
        '"result": "<win|draw|loss or null>", "line": ["<uci>", "..."], '
        '"explanation": "<one or two sentences>"}\n'
        "```\n"
        "Fill only the fields relevant to the task; use null for the rest. The "
        "best_move, eval_bucket and result must match what analyze_position returned. "
        "For deep_line, use legal UCI moves and make the first line move match "
        "best_move."
    )


# The skill that carries the Socratic teaching method and spoiler control. A teaching
# turn is answered *only* through it, so a structured skill can't blurt the move when
# the student asked for a hint.
_INTERACTIVE_SKILL = "interactive-coach"

_TEACH_SYSTEM_PROMPT = (
    "You are a chess coach helping a student in a single coaching turn. Teach through "
    "the reply: when the student asks for a hint or a nudge, guide them toward the "
    "idea with a pointer or a question and do NOT state the best move; when they ask "
    "directly, are stuck, or propose a move, answer plainly and then explain. Never "
    "invent concrete facts — the best move, who is better, an endgame result — verify "
    "them with your tools first, then speak. Reply in warm, natural prose (no JSON)."
)

_CONVERSATION_SYSTEM_PROMPT = (
    "You are a chess coach in a multi-turn lesson. Use the prior transcript as "
    "context: remember the student's goals, misconceptions, earlier hints, and any "
    "candidate moves already discussed. If a FEN is provided, verify concrete claims "
    "about the position with your tools before stating them. If no FEN is provided, "
    "answer only from general chess principles and say when a board position would "
    "be needed. Reply in natural coaching prose, not JSON."
)


def _build_teach_prompt(fen: str, message: str, level: str | None) -> str:
    lvl = f" The student is a {level} player." if level else ""
    return (
        f"Position (FEN): {fen}.{lvl}\n"
        f'The student says: "{message}"\n'
        "Respond as their coach."
    )


_GENERAL_CHAT_SYSTEM_PROMPT = (
    "You are a rigorous chess coach answering general chess questions, not a board "
    "position. Give factual, source-respecting chess instruction in natural prose, "
    "pitched to the student's level. Do not invent book quotations, exact statistics, "
    "engine claims, or rules you are unsure about. If a question would require a "
    "specific position to answer concretely, say what information is missing and "
    "give the useful general principle."
)


def _build_general_chat_prompt(message: str, level: str | None) -> str:
    lvl = f"\nThe student is a {level} player." if level else ""
    return (
        f"{lvl}\n"
        f'The student asks: "{message}"\n'
        "Respond as their chess coach. Keep the answer practical, accurate, and "
        "clear enough that the student can turn it into training action."
    )


def _build_conversation_prompt(
    fen: str | None,
    history: list[tuple[str, str]],
    message: str,
    level: str | None,
) -> str:
    lvl = f"\nThe student is a {level} player." if level else ""
    position = (
        f"Current position (FEN): {fen}\n"
        if fen
        else "No current FEN is provided.\n"
    )
    transcript = "\n".join(f"{role}: {text}" for role, text in history)
    if transcript:
        transcript = f"Conversation so far:\n{transcript}\n"
    return (
        f"{position}{lvl}\n"
        f"{transcript}"
        f'Student now says: "{message}"\n'
        "Respond as their coach, using the conversation history."
    )


class AgentCoach:
    """A Claude coaching agent grounded in Stockfish + opening theory.

    Construct it with an already-open :class:`PositionAnalyzer` and an
    :class:`OpeningBook`; call :meth:`answer` (or :meth:`answer_sync`) per position.
    """

    def __init__(
        self,
        analyzer: PositionAnalyzer,
        book: OpeningBook | None = None,
        *,
        tablebase: Tablebase | None = None,
        model: str = DEFAULT_MODEL,
        skills: list[str] | None = None,
        max_turns: int = 8,
    ) -> None:
        # Memoize + enable prefetch: a turn analyses the same FEN more than once, and
        # we warm the engine the moment the position is known (compute over latency).
        self._analyzer = (
            analyzer
            if isinstance(analyzer, MemoizingAnalyzer)
            else MemoizingAnalyzer(analyzer)
        )
        self._book = book or OpeningBook()
        self._tablebase = tablebase or Tablebase()
        self._model = model
        self._skills = skills if skills is not None else list(DEFAULT_SKILLS)
        self._max_turns = max_turns

    def _options(self) -> ClaudeAgentOptions:
        server = _chess_tools(self._analyzer, self._book, self._tablebase)
        return ClaudeAgentOptions(
            model=self._model,
            system_prompt=_SYSTEM_PROMPT,
            mcp_servers={_MCP_SERVER: server},
            # Tool filtering at the agent boundary: the coach may use *only* the
            # chess kernel tools; each skill narrows that further in its frontmatter.
            # Everything else (shell, web, files) is off the table.
            allowed_tools=list(_ALL_TOOLS),
            disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
            permission_mode="bypassPermissions",
            skills=self._skills,
            setting_sources=["project"],
            max_turns=self._max_turns,
            # Empty unless native subprocess telemetry is enabled; the SDK merges it
            # over the inherited environment, so {} is a no-op.
            env=tracing.claude_env(),
        )

    async def answer(
        self,
        fen: str,
        task_type: str,
        level: str | None = None,
        question: str | None = None,
        candidate_move: str | None = None,
    ) -> CoachAnswer:
        """Run the agent on one position and return its structured answer."""
        prompt = _build_prompt(fen, task_type, level, question, candidate_move)
        final = ""
        transcript: list[str] = []
        with tracing.turn_span(
            "coach.answer", _turn_attrs(self._model, fen, task_type, level)
        ) as span:
            async with anyio.create_task_group() as tg:
                # Warm the engine while the model reads the prompt, so its first
                # analyze_position call hits a ready result instead of waiting.
                tg.start_soon(anyio.to_thread.run_sync, self._analyzer.prefetch, fen)
                async for message in query(prompt=prompt, options=self._options()):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                transcript.append(block.text)
                    elif isinstance(message, ResultMessage):
                        final = message.result or ""
                        tracing.record_result(span, message)
        text = final or "\n".join(transcript)
        return _parse_answer(text)

    def answer_sync(
        self,
        fen: str,
        task_type: str,
        level: str | None = None,
        question: str | None = None,
        candidate_move: str | None = None,
    ) -> CoachAnswer:
        """Blocking convenience wrapper around :meth:`answer`."""
        return anyio.run(self.answer, fen, task_type, level, question, candidate_move)

    def _interactive_options(self) -> ClaudeAgentOptions:
        """Options for a single teaching turn: interactive-coach only, prose reply."""
        server = _chess_tools(self._analyzer, self._book, self._tablebase)
        return ClaudeAgentOptions(
            model=self._model,
            system_prompt=_TEACH_SYSTEM_PROMPT,
            mcp_servers={_MCP_SERVER: server},
            allowed_tools=list(_ALL_TOOLS),
            disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
            permission_mode="bypassPermissions",
            skills=[_INTERACTIVE_SKILL],
            setting_sources=["project"],
            max_turns=self._max_turns,
            env=tracing.claude_env(),
        )

    def _general_chat_options(self) -> ClaudeAgentOptions:
        """Options for non-position chess Q&A: prose reply, no board tools."""
        return ClaudeAgentOptions(
            model=self._model,
            system_prompt=_GENERAL_CHAT_SYSTEM_PROMPT,
            allowed_tools=[],
            disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
            permission_mode="bypassPermissions",
            skills=[_INTERACTIVE_SKILL],
            setting_sources=["project"],
            max_turns=self._max_turns,
            env=tracing.claude_env(),
        )

    async def teach(self, fen: str, message: str, level: str | None = None) -> str:
        """Answer one student turn as the interactive coach — prose, spoiler-aware.

        Unlike :meth:`answer`, this loads only the ``interactive-coach`` skill and asks
        for a natural-language reply (no JSON), so the Socratic method and spoiler
        control decide what to reveal.
        """
        prompt = _build_teach_prompt(fen, message, level)
        final = ""
        transcript: list[str] = []
        with tracing.turn_span(
            "coach.teach", _turn_attrs(self._model, fen, "explain", level)
        ) as span:
            async with anyio.create_task_group() as tg:
                tg.start_soon(anyio.to_thread.run_sync, self._analyzer.prefetch, fen)
                async for msg in query(
                    prompt=prompt, options=self._interactive_options()
                ):
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                transcript.append(block.text)
                    elif isinstance(msg, ResultMessage):
                        final = msg.result or ""
                        tracing.record_result(span, msg)
        return final or "\n".join(transcript)

    def teach_sync(self, fen: str, message: str, level: str | None = None) -> str:
        """Blocking convenience wrapper around :meth:`teach`."""
        return anyio.run(self.teach, fen, message, level)

    async def general_chat(self, message: str, level: str | None = None) -> str:
        """Answer a non-position chess coaching question in prose."""
        prompt = _build_general_chat_prompt(message, level)
        final = ""
        transcript: list[str] = []
        with tracing.turn_span(
            "coach.general_chat", _turn_attrs(self._model, None, "general_chat", level)
        ) as span:
            async for msg in query(prompt=prompt, options=self._general_chat_options()):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            transcript.append(block.text)
                elif isinstance(msg, ResultMessage):
                    final = msg.result or ""
                    tracing.record_result(span, msg)
        return final or "\n".join(transcript)

    def _conversation_options(self) -> ClaudeAgentOptions:
        """Options for a multi-turn eval transcript supplied in one prompt."""
        server = _chess_tools(self._analyzer, self._book, self._tablebase)
        return ClaudeAgentOptions(
            model=self._model,
            system_prompt=_CONVERSATION_SYSTEM_PROMPT,
            mcp_servers={_MCP_SERVER: server},
            allowed_tools=list(_ALL_TOOLS),
            disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
            permission_mode="bypassPermissions",
            skills=[_INTERACTIVE_SKILL],
            setting_sources=["project"],
            max_turns=self._max_turns,
            env=tracing.claude_env(),
        )

    async def converse(
        self,
        fen: str | None,
        history: list[tuple[str, str]],
        message: str,
        level: str | None = None,
    ) -> str:
        """Answer the next turn in a supplied multi-turn conversation transcript."""
        prompt = _build_conversation_prompt(fen, history, message, level)
        final = ""
        transcript: list[str] = []
        with tracing.turn_span(
            "coach.converse", _turn_attrs(self._model, fen or "", "conversation", level)
        ) as span:
            async with anyio.create_task_group() as tg:
                if fen:  # a conversation turn may carry no board
                    tg.start_soon(
                        anyio.to_thread.run_sync, self._analyzer.prefetch, fen
                    )
                async for msg in query(
                    prompt=prompt, options=self._conversation_options()
                ):
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                transcript.append(block.text)
                    elif isinstance(msg, ResultMessage):
                        final = msg.result or ""
                        tracing.record_result(span, msg)
        return final or "\n".join(transcript)

    def general_chat_sync(self, message: str, level: str | None = None) -> str:
        """Blocking convenience wrapper around :meth:`general_chat`."""
        return anyio.run(self.general_chat, message, level)

    def converse_sync(
        self,
        fen: str | None,
        history: list[tuple[str, str]],
        message: str,
        level: str | None = None,
    ) -> str:
        """Blocking convenience wrapper around :meth:`converse`."""
        return anyio.run(self.converse, fen, history, message, level)


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"(\{[^{}]*\"explanation\"[^{}]*\})", re.DOTALL)


def _parse_answer(text: str) -> CoachAnswer:
    """Extract the final JSON answer from the model's message.

    Prefers the last fenced ```json block; falls back to a bare JSON object that
    carries an ``explanation`` key. Raises :class:`CoachAgentError` if neither is
    present, so a silent malformed answer can never be scored as a pass.
    """
    candidates = _JSON_BLOCK.findall(text) or _BARE_JSON.findall(text)
    for blob in reversed(candidates):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        return CoachAnswer(
            best_move=_clean(data.get("best_move")),
            eval_bucket=_clean(data.get("eval_bucket")),
            result=_clean(data.get("result")),
            line=_clean_line(data.get("line")),
            explanation=str(data.get("explanation") or "").strip(),
            raw=text,
        )
    raise CoachAgentError(f"no parseable JSON answer in agent output:\n{text[:500]}")


def _clean(value: object) -> str | None:
    """Normalise a field: treat null/empty/'none' as absent."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    return text


def _clean_line(value: object) -> list[str] | None:
    """Normalise a JSON line field to a non-empty list of move strings."""
    if value is None:
        return None
    if isinstance(value, list):
        line = [str(move).strip() for move in value if str(move).strip()]
        return line or None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none", "n/a"}:
            return None
        line = [move for move in re.split(r"[,\s]+", text) if move]
        return line or None
    return None

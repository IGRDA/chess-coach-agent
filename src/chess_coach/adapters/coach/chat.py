"""A stateful coaching conversation: one Claude agent that remembers the dialogue.

The one-shot coach (:class:`~chess_coach.adapters.coach.agent.AgentCoach`) spins up a
fresh, stateless run per question. Live coaching needs the opposite — a session that
holds the thread of the conversation so the student can think out loud, try a move, ask
a follow-up, and be understood in context. :class:`ChatSession` wraps a persistent
``ClaudeSDKClient`` for exactly that, and streams the reply so the front-end can render
it as the coach speaks.

Deep module: open it as an async context manager, then call :meth:`stream` per student
turn. Hidden inside are the same in-process chess tools the one-shot coach uses (all
six, with their blocking engine calls kept off the event loop), the
``interactive-coach`` skill that carries the Socratic teaching method, and the tight
tool allowlist — the coach may touch only the chess kernel, nothing else.

Also hidden here is the latency work, because a live conversation is judged on how
long the student stares at a blank panel. A turn's wall time is dominated by two
things: the round trips the model takes *before* it can start writing, and the rate it
writes at. The second is not ours to change without changing what the coach says, so
this module attacks the first — the reply is streamed token by token instead of
arriving in one block at the end, the coaching method is handed over up front instead
of fetched with a ``Skill`` call, and the built-in tool set is trimmed to nothing so
tool discovery is not deferred behind a ``ToolSearch``. Measured over the TUI's own
question shapes, that moved time-to-first-word from ~18s to ~8s with the coach's
grounding, legality and spoiler control unchanged. See :class:`ChatSession`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
)

from chess_coach.adapters.coach.agent import (
    _ALL_TOOLS,
    _MCP_SERVER,
    DEFAULT_MODEL,
    _chess_tools,
    _turn_attrs,
)
from chess_coach.adapters.coach.analysis import MemoizingAnalyzer, PositionAnalyzer
from chess_coach.adapters.coach.opening_book import OpeningBook
from chess_coach.adapters.coach.prefetch import PositionPrefetcher
from chess_coach.adapters.coach.prompts import (
    CLAUDE_CHAT_SYSTEM_PROMPT,
    build_claude_chat_prompt,
)
from chess_coach.adapters.coach.tablebase import Tablebase
from chess_coach.adapters.observability import tracing

_CHAT_SYSTEM_PROMPT = CLAUDE_CHAT_SYSTEM_PROMPT
_build_chat_prompt = build_claude_chat_prompt

# ``max_turns`` is a budget for the whole *session*, not one student turn: the SDK
# counts agent turns across every query on the client. At the old value of 8 a single
# tool-heavy opening question exhausted it, and every later turn in the conversation
# came back empty — the live coach went mute mid-lesson. A coaching conversation is
# many turns long, so the budget is sized for the conversation; it remains a runaway
# guard, not a per-question limit.
_SESSION_MAX_TURNS = 200

# Project skills live beside the code, not beside the working directory: the coach
# must load the same method whatever directory the app was launched from.
_SKILLS_DIR = Path(__file__).resolve().parents[4] / ".claude" / "skills"


def _skill_body(name: str) -> str:
    """The instructions inside a project skill, ready to paste into a system prompt.

    Loading a skill the usual way is *progressive disclosure*: the model is told the
    skill exists, then spends a round trip calling ``Skill`` to read it. That trade is
    right when a model must choose among many skills — and pointless here, where the
    live coach always wants exactly one, every turn, before it can say anything.

    Inlining hands the model the same instructions up front. The YAML frontmatter is
    dropped: its ``description`` only helps a model *pick* a skill, and its
    ``allowed-tools`` list is enforced by the agent options either way.
    """
    path = _SKILLS_DIR / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, _, rest = text.partition("---")
        _, _, text = rest.partition("---")
    return text.strip()


def _text_delta(event: StreamEvent) -> str | None:
    """The visible text carried by a raw stream event, if it carries any.

    Only ``text_delta`` counts: thinking deltas and block bookkeeping are not part of
    what the student reads.
    """
    ev = event.event
    if ev.get("type") != "content_block_delta":
        return None
    delta = ev.get("delta") or {}
    if delta.get("type") != "text_delta":
        return None
    return delta.get("text") or None


class ChatSession:
    """An open coaching conversation over a persistent Claude agent client.

    ``token_stream``, ``direct_tools`` and ``inline_skills`` are latency options. All
    three leave *what* the coach says untouched — same instructions, same tools, same
    engine ground truth — and change only how soon the student reads it, by removing
    round trips that happen before the coach can speak. They default on; each is
    switchable so the pair can be measured against each other.
    """

    def __init__(
        self,
        analyzer: PositionAnalyzer,
        book: OpeningBook | None = None,
        *,
        tablebase: Tablebase | None = None,
        model: str = DEFAULT_MODEL,
        skills: list[str] | None = None,
        max_turns: int = _SESSION_MAX_TURNS,
        token_stream: bool = True,
        direct_tools: bool = True,
        inline_skills: bool = True,
    ) -> None:
        # Memoize unconditionally: a single turn analyses the same FEN more than once
        # (the best move, then a move the student is weighing), and the prefetcher
        # needs somewhere to put the warm result. Deterministic given the FEN, so the
        # coach reads exactly what a fresh search would have returned.
        self._analyzer = (
            analyzer
            if isinstance(analyzer, MemoizingAnalyzer)
            else MemoizingAnalyzer(analyzer)
        )
        self._book = book or OpeningBook()
        self._tablebase = tablebase or Tablebase()
        self._model = model
        self._skills = skills if skills is not None else ["interactive-coach"]
        self._max_turns = max_turns
        self._token_stream = token_stream
        self._direct_tools = direct_tools
        self._inline_skills = inline_skills
        self._prefetcher = PositionPrefetcher(self._analyzer)
        self._client: ClaudeSDKClient | None = None

    def _system_prompt(self) -> str:
        """The coach's standing instructions, with the method inlined when asked."""
        if not self._inline_skills:
            return _CHAT_SYSTEM_PROMPT
        return "\n\n".join(
            [_CHAT_SYSTEM_PROMPT, *(_skill_body(name) for name in self._skills)]
        )

    def _options(self) -> ClaudeAgentOptions:
        server = _chess_tools(self._analyzer, self._book, self._tablebase)
        # With the method already inlined there is nothing left for `Skill` to fetch,
        # so the built-in set can go empty; otherwise `Skill` has to stay. Either way
        # the other two dozen built-ins (shell, files, tasks, cron…) are dropped —
        # the coach was already forbidden every one of them, and it is their bulk that
        # makes the CLI *defer* tool discovery, costing a `ToolSearch` round trip
        # before the model can even reach the chess kernel.
        builtins: list[str] = [] if self._inline_skills else ["Skill"]
        return ClaudeAgentOptions(
            model=self._model,
            system_prompt=self._system_prompt(),
            mcp_servers={_MCP_SERVER: server},
            tools=builtins if self._direct_tools else None,
            allowed_tools=list(_ALL_TOOLS),
            disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
            permission_mode="bypassPermissions",
            # Inlined instructions are already in the system prompt; announcing the
            # skills too would just invite the round trip we removed.
            skills=[] if self._inline_skills else self._skills,
            setting_sources=["project"],
            max_turns=self._max_turns,
            # Deliver the reply as it is generated rather than in one block at the
            # end. The coach says exactly the same thing either way; the student just
            # starts reading seconds in instead of watching a blank panel.
            include_partial_messages=self._token_stream,
            env=tracing.claude_env(),
        )

    async def __aenter__(self) -> ChatSession:
        self._client = ClaudeSDKClient(options=self._options())
        await self._client.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._prefetcher.close()
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def stream(
        self, fen: str, message: str, level: str | None = None
    ) -> AsyncIterator[str]:
        """Send one student turn and yield the coach's reply text as it arrives.

        The same client is reused across turns, so the conversation is remembered; the
        current FEN is threaded in each turn so the coach always sees the live board.

        With ``token_stream`` on, the chunks are token deltas as the model writes;
        otherwise they are whole message blocks. The concatenation is identical — only
        the granularity, and so the time to the student's first word, differs.
        """
        if self._client is None:
            raise RuntimeError("ChatSession used outside an `async with` block")
        prompt = _build_chat_prompt(fen, message, level)
        await self._client.query(prompt)
        output_chunks: list[str] = []
        final = ""
        with tracing.turn_span(
            "coach.chat", _turn_attrs(self._model, fen, "explain", level)
        ) as span:
            tracing.record_turn_context(
                span,
                input_value=prompt,
                provider="claude",
                system_prompt=_CHAT_SYSTEM_PROMPT,
                skills=self._skills,
                skill_mode="inline" if self._inline_skills else "dynamic",
            )
            async for msg in self._client.receive_response():
                if isinstance(msg, StreamEvent):
                    text = _text_delta(msg)
                    if text:
                        output_chunks.append(text)
                        yield text
                elif isinstance(msg, AssistantMessage):
                    tracing.record_model_message(span, msg)
                    # Already yielded delta by delta when token streaming is on;
                    # re-yielding the assembled block would duplicate the reply.
                    if not self._token_stream:
                        for block in msg.content:
                            if isinstance(block, TextBlock) and block.text:
                                output_chunks.append(block.text)
                                yield block.text
                elif isinstance(msg, ResultMessage):
                    final = msg.result or ""
                    tracing.record_result(span, msg)
            tracing.record_output(span, final or "".join(output_chunks))
            tracing.mark_ok(span)

    def prefetch(self, fen: str) -> None:
        """Warm the engine for ``fen`` in the background; returns immediately.

        Call it whenever the board changes. By the time the student has typed their
        question, ``analyze_position`` reads a cached search instead of starting one.
        """
        self._prefetcher.schedule(fen)

    def assess(self, fen: str) -> str:
        """The engine's assessment bucket — a direct read for revealing ground truth."""
        return self._analyzer.analyze(fen).bucket

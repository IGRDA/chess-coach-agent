"""The coach's tool sandbox: it can reach the chess kernel and nothing else.

These guard an invariant the evaluation depends on — the agent has *no*
filesystem, shell, or web tool, so it cannot read the goldens it is graded
against and parrot the answer key. The control lives entirely in the tool
allowlist/denylist of every ``ClaudeAgentOptions`` the coach builds
(``agent.py``); a future edit that widens ``allowed_tools`` or drops a name
from ``disallowed_tools`` must break a test here, not the eval silently.
"""

from __future__ import annotations

import pytest

from chess_coach.adapters.coach import agent as agent_mod
from chess_coach.adapters.coach.agent import AgentCoach

# Tools that would let the agent read the answer key (or exfiltrate/escape the
# sandbox). None of these may ever appear in an allowlist, and each must be
# named in every denylist.
_FORBIDDEN = {"Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"}
_MCP_PREFIX = f"mcp__{agent_mod._MCP_SERVER}__"


class _StubAnalyzer:
    """Placeholder analyzer: the options builders close over it but never call it."""

    def analyze(self, fen: str) -> object:  # pragma: no cover - never invoked
        raise AssertionError("the analyzer must not be called while building options")


@pytest.fixture
def coach() -> AgentCoach:
    return AgentCoach(_StubAnalyzer())


def _all_options(coach: AgentCoach) -> dict[str, object]:
    """Every ClaudeAgentOptions the coach hands to the SDK, keyed by entry point."""
    return {
        "answer": coach._options(),
        "teach": coach._interactive_options(),
        "general_chat": coach._general_chat_options(),
        "converse": coach._conversation_options(),
    }


def test_all_tools_constant_is_only_the_chess_kernel() -> None:
    """The allowlist source is exactly the six ``mcp__chess__*`` tools — no others."""
    assert agent_mod._ALL_TOOLS
    assert all(name.startswith(_MCP_PREFIX) for name in agent_mod._ALL_TOOLS)


def test_move_evaluation_is_reachable_from_every_position_entry_point(
    coach: AgentCoach,
) -> None:
    """Judging a concrete move is a coaching primitive, not an optional extra.

    Every entry point that carries a board must expose it; ``general_chat`` has no
    position, so it is excluded by design (asserted separately).
    """
    positional = {k: v for k, v in _all_options(coach).items() if k != "general_chat"}
    for name, options in positional.items():
        assert agent_mod._EVALUATE in (options.allowed_tools or []), (
            f"{name} cannot evaluate a concrete move"
        )


def test_the_evaluate_move_tool_name_matches_the_mcp_convention() -> None:
    assert agent_mod._EVALUATE == f"{_MCP_PREFIX}evaluate_move"
    assert agent_mod._EVALUATE in agent_mod._ALL_TOOLS


def test_no_options_allowlist_grants_a_file_or_shell_tool(coach: AgentCoach) -> None:
    for name, options in _all_options(coach).items():
        allowed = set(options.allowed_tools or [])
        leaked = allowed & _FORBIDDEN
        assert not leaked, f"{name} allowlist leaks {leaked}"


def test_allowlists_contain_only_chess_kernel_tools(coach: AgentCoach) -> None:
    """Whatever is allowed is a chess-kernel tool; the allowlist is a pure whitelist."""
    for name, options in _all_options(coach).items():
        allowed = options.allowed_tools or []
        stray = [t for t in allowed if not t.startswith(_MCP_PREFIX)]
        assert not stray, f"{name} allows non-kernel tools {stray}"


def test_every_options_denies_the_forbidden_tools(coach: AgentCoach) -> None:
    """Defense in depth: the file/shell/web tools are explicitly turned off too."""
    for name, options in _all_options(coach).items():
        disallowed = set(options.disallowed_tools or [])
        missing = _FORBIDDEN - disallowed
        assert not missing, f"{name} fails to deny {missing}"


def test_general_chat_has_no_tools_at_all(coach: AgentCoach) -> None:
    """The non-position path needs no engine, so it grants an empty allowlist."""
    assert coach._general_chat_options().allowed_tools == []

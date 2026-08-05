"""Coaching actions: turn a coach-panel button into a message for the conversation.

The panel offers a handful of actions; this module is the single place that phrases
each as something the student "says" to the coach. Keeping the wording here (pure,
engine-free) means the widgets just name an action and the chat session carries the
dialogue. The one-shot ``CoachingRequest`` path still lives in the application layer for
the CLI; the TUI now talks to the coach in natural turns.
"""

from __future__ import annotations

HINT = "hint"
EXPLAIN = "explain"
CHALLENGE = "challenge"
ASK = "ask"

_LABELS: dict[str, str] = {
    HINT: "Hint",
    EXPLAIN: "Explain position",
    CHALLENGE: "Challenge idea",
    ASK: "Question",
}

_HINT_MESSAGE = (
    "Give me a hint about what to look for in this position — a nudge toward the idea, "
    "not the answer. Don't tell me the best move yet."
)
_EXPLAIN_MESSAGE = (
    "Explain this position: the key features, the plans for both sides, and who stands "
    "better and why."
)


class CoachActionError(ValueError):
    """Raised when an action can't be turned into a message (bad or incomplete)."""


def message_for(
    action: str, *, text: str = "", candidate_move: str | None = None
) -> str:
    """Phrase a coach-panel ``action`` as the student's turn in the conversation."""
    typed = text.strip()
    if action == HINT:
        return _HINT_MESSAGE
    if action == EXPLAIN:
        return _EXPLAIN_MESSAGE
    if action == CHALLENGE:
        move = (candidate_move or typed) or None
        if not move:
            raise CoachActionError("challenge needs a candidate move to critique")
        return f"I'm considering {move}. Is it a good move, and what am I missing?"
    if action == ASK:
        if not typed:
            raise CoachActionError("ask needs a question")
        return typed
    raise CoachActionError(f"unknown coach action: {action!r}")


def action_label(action: str) -> str:
    """A human-readable name for an action (falls back to the raw token)."""
    return _LABELS.get(action, action)

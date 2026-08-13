"""Streaming granularity is a delivery choice, not a change to what the coach says."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import StreamEvent

from chess_coach.adapters.coach.chat import _text_delta


def _event(payload: dict[str, Any]) -> StreamEvent:
    return StreamEvent(uuid="u", session_id="s", event=payload)


def test_text_deltas_are_the_visible_reply() -> None:
    event = _event(
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Nf3 develops"},
        }
    )
    assert _text_delta(event) == "Nf3 develops"


def test_thinking_is_not_shown_to_the_student() -> None:
    event = _event(
        {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "let me check the pin"},
        }
    )
    assert _text_delta(event) is None


def test_block_bookkeeping_carries_no_text() -> None:
    for payload in (
        {"type": "content_block_start", "content_block": {"type": "text"}},
        {"type": "content_block_stop"},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": ""}},
    ):
        assert _text_delta(_event(payload)) is None


def test_deltas_concatenate_to_the_whole_reply() -> None:
    """The student must read exactly the message the coach wrote, in order."""
    reply = "The knight on f6 is pinned, so d5 comes with tempo."
    events = [
        _event(
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": chunk},
            }
        )
        for chunk in (reply[i : i + 7] for i in range(0, len(reply), 7))
    ]
    assert "".join(t for e in events if (t := _text_delta(e))) == reply

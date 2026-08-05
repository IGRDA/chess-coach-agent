"""Coaching-mapping tests: UI action -> the student's message in the conversation.

The coach panel exposes a few actions (hint, explain, challenge a move, ask a
free-form question). This module turns each into the message the student "says" to
the live coach. Pure mapping, no engine.
"""

from __future__ import annotations

import pytest

from chess_coach.interface.tui import coaching


def test_hint_asks_for_a_nudge_not_the_move() -> None:
    message = coaching.message_for(coaching.HINT)
    assert "hint" in message.lower()
    assert "not the answer" in message.lower()


def test_explain_asks_for_the_features_and_the_verdict() -> None:
    message = coaching.message_for(coaching.EXPLAIN)
    assert "who stands better" in message.lower()


def test_challenge_carries_the_candidate_move() -> None:
    message = coaching.message_for(coaching.CHALLENGE, candidate_move="e2e4")
    assert "e2e4" in message


def test_challenge_falls_back_to_typed_text_as_the_move() -> None:
    message = coaching.message_for(coaching.CHALLENGE, text="Nf3")
    assert "Nf3" in message


def test_challenge_without_a_move_is_an_error() -> None:
    with pytest.raises(coaching.CoachActionError):
        coaching.message_for(coaching.CHALLENGE)


def test_ask_forwards_the_free_form_question() -> None:
    message = coaching.message_for(coaching.ASK, text="What are the candidate moves?")
    assert message == "What are the candidate moves?"


def test_ask_without_text_is_an_error() -> None:
    with pytest.raises(coaching.CoachActionError):
        coaching.message_for(coaching.ASK, text="   ")


def test_unknown_action_is_an_error() -> None:
    with pytest.raises(coaching.CoachActionError):
        coaching.message_for("bogus")


def test_action_label_is_human_readable() -> None:
    assert coaching.action_label(coaching.HINT) == "Hint"
    assert coaching.action_label(coaching.CHALLENGE) == "Challenge idea"

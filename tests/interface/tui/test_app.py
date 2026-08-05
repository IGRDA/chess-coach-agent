"""End-to-end TUI tests driven by Textual's Pilot.

Clicks through the real widgets against a fake coaching *conversation* injected at the
same seam the CLI uses, so the wiring — board edits, move play, and each coach action
feeding the live session — is exercised without Stockfish, Claude or the network. The
app is given a generous virtual terminal so every panel is laid out and clickable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from textual.widgets import Button, Input, Label

from chess_coach.interface.tui.app import CoachTUI
from chess_coach.interface.tui.board_state import BoardState

_SIZE = (170, 55)


class FakeChat:
    """A :class:`ChatCoachPort` double: records each turn, streams a canned reply."""

    def __init__(self) -> None:
        self.turns: list[tuple[str, str, str | None]] = []
        self.prefetched: list[str] = []

    async def stream(
        self, fen: str, message: str, level: str | None = None
    ) -> AsyncIterator[str]:
        self.turns.append((fen, message, level))
        yield "Let's look at this together."
        yield "Grounded thought about the position."

    def assess(self, fen: str) -> str:
        return "winning"

    def prefetch(self, fen: str) -> None:
        self.prefetched.append(fen)


class FakeOpenChat:
    """An :class:`OpenChatPort` double: records each turn, streams a canned reply."""

    def __init__(self) -> None:
        self.turns: list[str] = []

    async def stream(self, message: str) -> AsyncIterator[str]:
        self.turns.append(message)
        yield "Anything you like — here is an answer."


def _app(chat: FakeChat, open_chat: FakeOpenChat | None = None) -> CoachTUI:
    open_chat = open_chat or FakeOpenChat()

    @asynccontextmanager
    async def service(settings: object) -> AsyncIterator[FakeChat]:
        yield chat

    @asynccontextmanager
    async def open_service(settings: object) -> AsyncIterator[FakeOpenChat]:
        yield open_chat

    return CoachTUI(chat_service=service, open_chat_service=open_service)


async def _mounted(app: CoachTUI, pilot: object) -> None:
    """Wait for the chat session to finish connecting before acting."""
    await app.workers.wait_for_complete()


async def test_palette_stamp_places_a_piece() -> None:
    app = _app(FakeChat())
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.click("#tool-Q")
        await pilot.click("#sq-e4")

        assert app.board.piece_symbol_at("e4") == "Q"


async def test_eraser_removes_a_piece() -> None:
    app = _app(FakeChat())
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.click("#tool-erase")
        await pilot.click("#sq-d2")

        assert app.board.piece_symbol_at("d2") is None


async def test_playing_a_move_warms_the_engine_for_the_new_position() -> None:
    """The coach starts thinking when the board changes, not when it is asked."""
    chat = FakeChat()
    app = _app(chat)
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        await pilot.click("#sq-e2")
        await pilot.click("#sq-e4")

        assert app.board.fen() in chat.prefetched


async def test_an_illegal_position_is_not_sent_to_the_engine() -> None:
    """Mid-edit rubble is not worth a search — and the engine would reject it anyway."""
    chat = FakeChat()
    app = _app(chat)
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        chat.prefetched.clear()
        await pilot.click("#tool-erase")
        await pilot.click("#sq-e1")  # remove White's king

        assert chat.prefetched == []


async def test_play_mode_makes_a_move_and_updates_the_variation() -> None:
    app = _app(FakeChat())
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.click("#sq-e2")
        await pilot.click("#sq-e4")

        assert app.board.variation_san() == "1. e4"
        variation = str(app.query_one("#variation-value", Label).render())
        assert "1. e4" in variation


async def test_black_underpromotion_can_be_entered_after_flipping() -> None:
    app = _app(FakeChat())
    app.board = BoardState("6k1/5pp1/8/8/8/8/K1p1Q3/8 b - - 0 1")

    async with app.run_test(size=_SIZE) as pilot:
        await pilot.press("f")
        move_input = app.query_one("#move-input", Input)
        move_input.value = "c2c1n"
        await pilot.click("#move-input")
        await pilot.press("enter")
        await pilot.pause()

        assert app.board.last_move_uci() == "c2c1n"


async def test_explain_sends_a_turn_and_streams_the_reply() -> None:
    chat = FakeChat()
    app = _app(chat)
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        await pilot.click("#coach-explain")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert len(chat.turns) == 1
        fen, message, _ = chat.turns[0]
        assert fen == app.board.fen()
        assert "who stands better" in message.lower()


async def test_challenge_forwards_the_played_move() -> None:
    chat = FakeChat()
    app = _app(chat)
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        await pilot.click("#sq-e2")
        await pilot.click("#sq-e4")
        await pilot.click("#coach-challenge")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert "e2e4" in chat.turns[-1][1]


async def test_typed_question_is_forwarded_verbatim() -> None:
    chat = FakeChat()
    app = _app(chat)
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        await pilot.click("#question-input")
        app.query_one("#question-input", Input).value = "What is the plan for White?"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert chat.turns[-1][1] == "What is the plan for White?"


async def test_eval_reveal_reads_the_engine_on_demand() -> None:
    chat = FakeChat()
    app = _app(chat)
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        assert "hidden" in str(app.query_one("#eval-toggle", Button).label)

        await pilot.press("e")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert "winning" in str(app.query_one("#eval-toggle", Button).label)


async def test_flip_changes_orientation() -> None:
    app = _app(FakeChat())
    async with app.run_test(size=_SIZE) as pilot:
        assert app.board.orientation == "white"
        await pilot.press("f")
        await pilot.pause()

        assert app.board.orientation == "black"


async def test_flip_rebuilds_coordinate_labels() -> None:
    app = _app(FakeChat())
    async with app.run_test(size=_SIZE) as pilot:
        assert str(app.query_one("#file-label-0").render()) == "a"
        assert str(app.query_one("#rank-label-0").render()) == "8"

        await pilot.press("f")
        await pilot.pause()

        assert str(app.query_one("#file-label-0").render()) == "h"
        assert str(app.query_one("#rank-label-0").render()) == "1"


async def test_invalid_position_blocks_a_coach_call() -> None:
    chat = FakeChat()
    app = _app(chat)
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        await pilot.click("#tool-erase")
        await pilot.click("#sq-e1")  # remove White's king -> illegal position
        await pilot.click("#coach-explain")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert chat.turns == []


@pytest.mark.parametrize("button", ["ctl-undo", "ctl-reset", "ctl-clear", "ctl-turn"])
async def test_board_controls_do_not_raise(button: str) -> None:
    app = _app(FakeChat())
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.click("#sq-e2")
        await pilot.click("#sq-e4")
        await pilot.click(f"#{button}")
        await pilot.pause()


async def test_stamping_highlights_the_picked_palette_button() -> None:
    app = _app(FakeChat())
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.click("#tool-Q")
        await pilot.pause()

        picked = app.query_one("#tool-Q", Button)
        assert picked.has_class("picked")
        # No other palette button keeps the highlight.
        highlighted = [
            b.id
            for b in app.query(".palette-row Button").results(Button)
            if b.has_class("picked")
        ]
        assert highlighted == ["tool-Q"]


async def test_ask_anything_mode_routes_questions_to_open_chat() -> None:
    chat = FakeChat()
    open_chat = FakeOpenChat()
    app = _app(chat, open_chat)
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        await pilot.click("#mode-open")
        await app.workers.wait_for_complete()
        await pilot.click("#question-input")
        app.query_one("#question-input", Input).value = "What is the en passant rule?"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert open_chat.turns == ["What is the en passant rule?"]
        assert chat.turns == []  # the grounded coach never saw it


async def test_open_mode_hides_the_board_coach_buttons() -> None:
    app = _app(FakeChat())
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        assert not app.query_one("#coach-buttons").has_class("hidden")

        await pilot.click("#mode-open")
        await pilot.pause()
        assert app.query_one("#coach-buttons").has_class("hidden")

        await pilot.click("#mode-coach")
        await pilot.pause()
        assert not app.query_one("#coach-buttons").has_class("hidden")


async def test_new_conversation_clears_the_transcript_and_reconnects() -> None:
    from textual.widgets import RichLog

    chat = FakeChat()
    app = _app(chat)
    async with app.run_test(size=_SIZE) as pilot:
        await _mounted(app, pilot)
        await pilot.click("#coach-explain")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.query_one("#transcript", RichLog).lines  # something was written

        await pilot.click("#coach-new")
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Cleared, then the fresh session announces itself again.
        transcript = app.query_one("#transcript", RichLog)
        lines = "\n".join(str(line) for line in transcript.lines)
        assert "Grounded thought" not in lines
        assert "Coach ready" in lines

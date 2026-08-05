"""CoachTUI: the interactive terminal app — editable board + live coaching chat.

Wires the pure pieces together behind a Textual UI shaped like the product mockup:

* left — a piece palette split into two colour-banded trays (white pieces on a dark
  tray drawn in bright glyphs, black pieces on a light tray drawn in dark glyphs) so
  the side you are about to stamp is unmistakable, plus the board controls;
* centre — a click-editable, playable board (:class:`BoardWidget` over
  :class:`BoardState`) of dense, filled figurines on mid-tone squares; the palette
  selects a stamp piece, the eraser, or *play* mode (click a from-square then a
  to-square to make a legal move);
* right — a two-mode conversation panel. *Coach* is one open ``ChatCoachPort`` session,
  grounded in the engine and threaded with the live board; *Ask anything* is a
  board-free ``OpenChatPort`` for questions that have nothing to do with the position.
  A *New conversation* button clears the transcript and restarts the active session;
* bottom — the variation line, an eval reveal toggle (a direct, engine-only read), and
  an ephemeral notes box.

Both sessions are injected as factories so tests drive the whole app against fakes, and
production passes the Stockfish + Claude
:func:`~chess_coach.composition.container.chat_service` and
:func:`~chess_coach.composition.container.open_chat_service`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, RichLog

from chess_coach.application.ports.chat import ChatCoachPort
from chess_coach.application.ports.open_chat import OpenChatPort
from chess_coach.composition.config import Settings, load_settings
from chess_coach.composition.container import chat_service, open_chat_service
from chess_coach.interface.tui import coaching, rendering
from chess_coach.interface.tui.board_state import BoardState, IllegalMove
from chess_coach.interface.tui.widgets import BoardWidget, Square

# A factory that yields an open coaching conversation for the life of the app.
ChatServiceFactory = Callable[[Settings], AbstractAsyncContextManager[ChatCoachPort]]
# A factory that yields a free-form, board-free assistant conversation.
OpenChatServiceFactory = Callable[
    [Settings], AbstractAsyncContextManager[OpenChatPort]
]

_WHITE_PIECES = ("K", "Q", "R", "B", "N", "P")
_BLACK_PIECES = ("k", "q", "r", "b", "n", "p")

# The two conversation modes the coach panel can be in.
_MODE_COACH = "coach"
_MODE_OPEN = "open"

_COACH_PROMPT = "Talk to your coach about the board — ask, or think out loud."
_OPEN_PROMPT = "Ask anything at all — chess or not. No board attached."


class CoachTUI(App[None]):
    """The chess-coach terminal app."""

    CSS = """
    #main { height: 1fr; }

    #left { width: 30; padding: 0 1; }
    #left Button { width: 100%; height: 1; margin: 0; border: none; }
    #palette { height: auto; }

    /* Piece palette: two colour-banded trays so the side you are about to stamp
       is unmistakable — a light tray of dark-glyph black pieces, a dark tray of
       bright-glyph white pieces, each with a label. */
    .palette-band { height: auto; padding: 0 1; margin-bottom: 1; }
    .palette-band .band-label {
        width: 100%; height: 1; text-style: bold; content-align: left middle;
    }
    #left .palette-row { height: 1; width: 100%; }
    #left .palette-row Button {
        width: 1fr; min-width: 3; height: 1; padding: 0; border: none; margin: 0;
        text-style: bold; background: transparent;
    }
    #left .palette-row Button:hover { background: $boost; }
    #band-white { background: #26313f; }
    #band-white .band-label { color: #eef2f8; }
    #band-white .palette-row Button { color: #f6f8fc; }
    #band-black { background: #c7d2df; }
    #band-black .band-label { color: #1a2230; }
    #band-black .palette-row Button { color: #10141c; }
    #left .palette-row Button.picked { background: #f2d16b; color: #10141c; }

    #board {
        width: 50; height: 26;
        grid-size: 9 9;
        grid-columns: 2 6 6 6 6 6 6 6 6;
        grid-rows: 3 3 3 3 3 3 3 3 1;
        grid-gutter: 0;
    }
    CoordinateLabel {
        width: 100%; height: 100%;
        content-align: center middle;
        color: $text-muted; text-style: bold;
    }
    Square {
        width: 100%; height: 100%;
        content-align: center middle; text-style: bold;
    }
    /* Mid-tone squares so a bright-white and a near-black figurine both read
       clearly on either colour — the squares sit between the two piece shades. */
    Square.light { background: #aebfd2; }
    Square.dark { background: #6c8199; }
    Square.selected { background: #f2d16b; }
    Square.white { color: #ffffff; text-style: bold; }
    Square.black { color: #0c0f16; text-style: bold; }

    #coach { width: 1fr; padding: 0 1; }
    #coach-prompt { color: $text-muted; }
    #mode-tabs { height: 1; margin-bottom: 1; }
    #mode-tabs Button {
        width: 1fr; height: 1; border: none; margin: 0 1 0 0;
    }
    #mode-tabs Button.active { background: $primary; color: $text; text-style: bold; }
    #transcript { height: 1fr; border: round $primary; padding: 0 1; }
    #coach-buttons { height: auto; }
    #coach-buttons Button { width: 1fr; }
    #coach-buttons.hidden { display: none; }
    #coach-new { width: auto; min-width: 20; margin-top: 1; }
    #coach-status { color: $warning; height: 1; }

    #bottom { height: 3; border-top: solid $primary; padding: 0 1; }
    #variation-value { width: 1fr; }
    #notes-input { width: 30; }

    .section { text-style: bold; color: $secondary; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("f", "flip", "Flip"),
        ("u", "undo", "Undo"),
        ("r", "reset", "Reset"),
        ("e", "toggle_eval", "Eval"),
    ]

    def __init__(
        self,
        *,
        chat_service: ChatServiceFactory = chat_service,
        open_chat_service: OpenChatServiceFactory = open_chat_service,
        settings_loader: Callable[[], Settings] = load_settings,
        level: str | None = None,
    ) -> None:
        super().__init__()
        self.board = BoardState()
        self._chat_service = chat_service
        self._open_chat_service = open_chat_service
        self._settings_loader = settings_loader
        self.level = level
        self.tool = "play"
        self._from: str | None = None
        self.eval_revealed = False
        self._last_eval: str | None = None
        self.mode = _MODE_COACH
        self._chat: ChatCoachPort | None = None
        self._chat_cm: AbstractAsyncContextManager[ChatCoachPort] | None = None
        self._open: OpenChatPort | None = None
        self._open_cm: AbstractAsyncContextManager[OpenChatPort] | None = None

    # -- layout ----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            yield self._left_panel()
            yield BoardWidget(self.board)
            yield self._coach_panel()
        yield self._bottom_bar()
        yield Footer()

    def _left_panel(self) -> Vertical:
        return Vertical(
            Label("Pieces", classes="section"),
            self._palette(),
            Label("Board", classes="section"),
            Button("Flip", id="ctl-flip"),
            Button("Side to move", id="ctl-turn"),
            Button("Undo", id="ctl-undo"),
            Button("Reset", id="ctl-reset"),
            Button("Clear", id="ctl-clear"),
            Input(placeholder="castling e.g. KQkq", id="castling-input"),
            Input(placeholder="move e.g. Nf3 or g1f3", id="move-input"),
            Label(id="position-status"),
            Label(id="tool-status"),
            id="left",
        )

    def _palette(self) -> Vertical:
        return Vertical(
            self._piece_band("White pieces", _WHITE_PIECES, "band-white"),
            self._piece_band("Black pieces", _BLACK_PIECES, "band-black"),
            Button("Erase", id="tool-erase"),
            Button("Play moves", id="tool-play"),
            id="palette",
        )

    def _piece_band(
        self, label: str, pieces: tuple[str, ...], band_id: str
    ) -> Vertical:
        """A labelled, colour-banded tray of one side's stampable pieces.

        The tray's own ``band_id`` drives the glyph colour in CSS (bright on the
        dark white-tray, near-black on the light black-tray), so the side you are
        about to stamp is unmistakable before you touch the board.
        """
        return Vertical(
            Label(label, classes="band-label"),
            Horizontal(
                *[Button(rendering.piece_glyph(p), id=f"tool-{p}") for p in pieces],
                classes="palette-row",
            ),
            id=band_id,
            classes="palette-band",
        )

    def _coach_panel(self) -> Vertical:
        tabs = Horizontal(
            Button("Coach", id="mode-coach", classes="active"),
            Button("Ask anything", id="mode-open"),
            id="mode-tabs",
        )
        buttons = Horizontal(
            Button("Ask for hint", id="coach-hint"),
            Button("Explain position", id="coach-explain"),
            Button("Challenge idea", id="coach-challenge"),
            id="coach-buttons",
        )
        return Vertical(
            Label("Coach", classes="section"),
            tabs,
            Label(_COACH_PROMPT, id="coach-prompt"),
            RichLog(id="transcript", wrap=True, markup=False),
            Input(
                placeholder="Ask a question or type a candidate move…",
                id="question-input",
            ),
            buttons,
            Button("＋ New conversation", id="coach-new"),
            Label("", id="coach-status"),
            id="coach",
        )

    def _bottom_bar(self) -> Horizontal:
        return Horizontal(
            Label("Variations: —", id="variation-value"),
            Button("Evaluation: hidden ▾", id="eval-toggle"),
            Input(placeholder="Notes…", id="notes-input"),
            id="bottom",
        )

    def on_mount(self) -> None:
        self.title = "Chess Coach"
        self.sub_title = "improve your calculation"
        self._board_widget.redraw()
        self._refresh_status()
        self._refresh_bottom()
        self._connect_chat()

    # -- chat session lifecycle ------------------------------------------------

    @work(exclusive=True, group="chat-life")
    async def _connect_chat(self) -> None:
        """Open the coaching conversation once and hold it for the app's lifetime."""
        self._set_status("Connecting to coach…")
        try:
            self._chat_cm = self._chat_service(self._settings_loader())
            self._chat = await self._chat_cm.__aenter__()
        except Exception as exc:  # noqa: BLE001 — surface any wiring/engine failure
            self._chat_cm = None
            self._write_transcript(f"[coach unavailable] {exc}")
            self._set_status("")
            return
        self._set_status("")
        self._write_transcript("Coach ready. Set up a position and ask away.")
        # The board was drawn before the coach existed, so warm the opening position
        # now; every later change is warmed by `_refresh_status`.
        self._warm_coach()

    @work(exclusive=True, group="open-life")
    async def _connect_open_chat(self) -> None:
        """Open the free-form assistant conversation (lazily, on first use)."""
        self._set_status("Opening chat…")
        try:
            self._open_cm = self._open_chat_service(self._settings_loader())
            self._open = await self._open_cm.__aenter__()
        except Exception as exc:  # noqa: BLE001 — surface any wiring failure
            self._open_cm = None
            self._write_transcript(f"[chat unavailable] {exc}")
            self._set_status("")
            return
        self._set_status("")
        self._write_transcript("Ask me anything — chess or not.")

    async def on_unmount(self) -> None:
        await self._close_chat()
        await self._close_open_chat()

    async def _close_chat(self) -> None:
        if self._chat_cm is not None:
            with contextlib.suppress(Exception):  # teardown is best-effort
                await self._chat_cm.__aexit__(None, None, None)
            self._chat_cm = None
            self._chat = None

    async def _close_open_chat(self) -> None:
        if self._open_cm is not None:
            with contextlib.suppress(Exception):  # teardown is best-effort
                await self._open_cm.__aexit__(None, None, None)
            self._open_cm = None
            self._open = None

    # -- mode switching & new conversation -------------------------------------

    def _switch_mode(self, mode: str) -> None:
        """Point the input at the coach or the open chat, and reshape the panel."""
        if mode == self.mode:
            return
        self.mode = mode
        coaching_mode = mode == _MODE_COACH
        self.query_one("#mode-coach", Button).set_class(coaching_mode, "active")
        self.query_one("#mode-open", Button).set_class(not coaching_mode, "active")
        self.query_one("#coach-buttons").set_class(not coaching_mode, "hidden")
        self.query_one("#coach-prompt", Label).update(
            _COACH_PROMPT if coaching_mode else _OPEN_PROMPT
        )
        if not coaching_mode and self._open is None:
            self._connect_open_chat()

    @work(exclusive=True, group="reset")
    async def _new_conversation(self) -> None:
        """Clear the transcript and restart the *active* conversation from scratch."""
        self.query_one("#transcript", RichLog).clear()
        if self.mode == _MODE_COACH:
            await self._close_chat()
            self._connect_chat()
        else:
            await self._close_open_chat()
            self._connect_open_chat()

    # -- board interaction -----------------------------------------------------

    def on_square_clicked(self, message: Square.Clicked) -> None:
        square = message.square
        if self.tool == "play":
            self._play_click(square)
        elif self.tool == "erase":
            self.board.remove_piece(square)
            self._after_edit()
        else:
            self.board.set_piece(square, self.tool)
            self._after_edit()

    def _play_click(self, square: str) -> None:
        if self._from is None:
            if self.board.piece_symbol_at(square) is not None:
                self._from = square
                self._board_widget.redraw(selected=square)
            return
        if square == self._from:
            self._from = None
            self._board_widget.redraw()
            return
        origin, self._from = self._from, None
        try:
            self._make_move(origin, square)
        except IllegalMove:
            self.notify(f"Illegal move: {origin}{square}", severity="warning")
        self._board_widget.redraw()
        self._refresh_status()
        self._refresh_bottom()

    def _make_move(self, origin: str, dest: str) -> None:
        try:
            self.board.play(origin + dest)
        except IllegalMove:
            # Retry as a queen promotion; underpromotion goes through the move box.
            self.board.play(origin + dest + "q")

    def _after_edit(self) -> None:
        self._from = None
        self._board_widget.redraw()
        self._refresh_status()
        self._refresh_bottom()

    # -- buttons & inputs ------------------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("tool-"):
            self._select_tool(button_id.removeprefix("tool-"))
        elif button_id == "ctl-flip":
            await self.action_flip()
        elif button_id == "ctl-turn":
            self.board.set_turn("black" if self.board.turn == "white" else "white")
            self._after_edit()
        elif button_id == "ctl-undo":
            self.action_undo()
        elif button_id == "ctl-reset":
            self.action_reset()
        elif button_id == "ctl-clear":
            self.board.clear()
            self._after_edit()
        elif button_id == "eval-toggle":
            self.action_toggle_eval()
        elif button_id == "mode-coach":
            self._switch_mode(_MODE_COACH)
        elif button_id == "mode-open":
            self._switch_mode(_MODE_OPEN)
        elif button_id == "coach-new":
            self._new_conversation()
        elif button_id.startswith("coach-"):
            self._coach_action(button_id.removeprefix("coach-"))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        input_id = event.input.id
        if input_id == "move-input":
            try:
                self.board.play(event.value)
            except IllegalMove:
                self.notify(f"Illegal move: {event.value}", severity="warning")
            else:
                event.input.value = ""
                self._board_widget.redraw()
                self._refresh_status()
                self._refresh_bottom()
        elif input_id == "castling-input":
            self.board.set_castling(event.value)
            event.input.value = ""
            self._after_edit()
        elif input_id == "question-input":
            if self.mode == _MODE_OPEN:
                self._open_ask()
            else:
                self._coach_action(coaching.ASK)

    def _select_tool(self, tool: str) -> None:
        self.tool = tool
        self._from = None
        if tool == "play":
            label = "Play moves"
        elif tool == "erase":
            label = "Erase"
        else:
            colour = "white" if rendering.piece_is_white(tool) else "black"
            label = f"Stamp {colour} {rendering.piece_glyph(tool)}"
        self.query_one("#tool-status", Label).update(f"Tool: {label}")
        self._highlight_tool(f"tool-{tool}")
        self._board_widget.redraw()

    def _highlight_tool(self, button_id: str) -> None:
        """Mark the active palette button so the current stamp stays obvious."""
        for button in self.query(".palette-row Button").results(Button):
            button.set_class(button.id == button_id, "picked")

    # -- coaching --------------------------------------------------------------

    def _coach_action(self, action: str) -> None:
        if not self.board.is_valid():
            self.notify("Set up a legal position first.", severity="warning")
            return
        if self._chat is None:
            self.notify("Coach is still connecting…", severity="warning")
            return
        question = self.query_one("#question-input", Input)
        text = question.value
        candidate = None
        if action == coaching.CHALLENGE:
            candidate = text.strip() or self.board.last_move_uci()
        try:
            message = coaching.message_for(action, text=text, candidate_move=candidate)
        except coaching.CoachActionError as exc:
            self.notify(str(exc), severity="warning")
            return
        self._write_transcript(f"You: {message}")
        if action in (coaching.ASK, coaching.CHALLENGE):
            question.value = ""
        self._run_coach(message)

    @work(exclusive=True, group="coach")
    async def _run_coach(self, message: str) -> None:
        if self._chat is None:
            return
        self._set_busy(True)
        self._write_transcript("Coach:")
        try:
            async for chunk in self._chat.stream(self.board.fen(), message, self.level):
                self._write_transcript(chunk)
        except Exception as exc:  # noqa: BLE001 — surface anything to the panel
            self._write_transcript(f"[error] {exc}")
        finally:
            self._set_busy(False)

    # -- open chat (ask anything) ----------------------------------------------

    def _open_ask(self) -> None:
        if self._open is None:
            self.notify("Chat is still connecting…", severity="warning")
            return
        question = self.query_one("#question-input", Input)
        text = question.value.strip()
        if not text:
            return
        question.value = ""
        self._write_transcript(f"You: {text}")
        self._run_open(text)

    @work(exclusive=True, group="open")
    async def _run_open(self, message: str) -> None:
        if self._open is None:
            return
        self._set_busy(True)
        self._write_transcript("Assistant:")
        try:
            async for chunk in self._open.stream(message):
                self._write_transcript(chunk)
        except Exception as exc:  # noqa: BLE001 — surface anything to the panel
            self._write_transcript(f"[error] {exc}")
        finally:
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        who = "Assistant" if self.mode == _MODE_OPEN else "Coach"
        self._set_status(f"{who} is thinking…" if busy else "")
        for button_id in ("coach-hint", "coach-explain", "coach-challenge"):
            self.query_one(f"#{button_id}", Button).disabled = busy

    def _set_status(self, text: str) -> None:
        self.query_one("#coach-status", Label).update(text)

    # -- actions (key bindings) ------------------------------------------------

    async def action_flip(self) -> None:
        self.board.flip()
        await self._board_widget.relayout()

    def action_undo(self) -> None:
        self.board.undo()
        self._after_edit()

    def action_reset(self) -> None:
        self.board.reset()
        self._after_edit()

    def action_toggle_eval(self) -> None:
        self.eval_revealed = not self.eval_revealed
        if self.eval_revealed:
            self._reveal_eval()
        else:
            self._refresh_bottom()

    @work(exclusive=True, group="eval")
    async def _reveal_eval(self) -> None:
        """Read the engine's assessment of the current board on demand."""
        self._last_eval = None
        if self._chat is not None and self.board.is_valid():
            try:
                self._last_eval = await asyncio.to_thread(
                    self._chat.assess, self.board.fen()
                )
            except Exception:  # noqa: BLE001 — a failed probe just shows nothing
                self._last_eval = None
        self._refresh_bottom()

    # -- redraw helpers --------------------------------------------------------

    def _refresh_status(self) -> None:
        validity = "legal" if self.board.is_valid() else "illegal — fix it"
        self.query_one("#position-status", Label).update(
            f"{self.board.turn.capitalize()} to move · {validity}"
        )
        self._warm_coach()

    def _warm_coach(self) -> None:
        """Start the engine on the position now showing, so the next ask is quicker.

        Every board change lands here, which is exactly the signal we want: the coach
        will be asked about whatever is on the board, so it may as well start looking
        while the student is still deciding what to type. Fire-and-forget — the coach
        works identically if the warm-up never finishes.
        """
        if self._chat is None or not self.board.is_valid():
            return
        with contextlib.suppress(Exception):  # a warm-up must never break the UI
            self._chat.prefetch(self.board.fen())

    def _refresh_bottom(self) -> None:
        variation = rendering.format_variation(self.board.variation_san())
        self.query_one("#variation-value", Label).update(f"Variations: {variation}")
        shown = rendering.format_eval(self._last_eval, revealed=self.eval_revealed)
        caret = "▴" if self.eval_revealed else "▾"
        self.query_one("#eval-toggle", Button).label = f"Evaluation: {shown} {caret}"

    def _write_transcript(self, text: str) -> None:
        if text:
            self.query_one("#transcript", RichLog).write(text)

    @property
    def _board_widget(self) -> BoardWidget:
        return self.query_one(BoardWidget)


def run(
    *,
    chat_service: ChatServiceFactory = chat_service,
    open_chat_service: OpenChatServiceFactory = open_chat_service,
    settings_loader: Callable[[], Settings] = load_settings,
    level: str | None = None,
) -> None:
    """Launch the interactive coach TUI (blocks until the user quits)."""
    CoachTUI(
        chat_service=chat_service,
        open_chat_service=open_chat_service,
        settings_loader=settings_loader,
        level=level,
    ).run()

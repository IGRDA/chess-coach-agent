"""Board widgets: the clickable 8x8 grid.

Thin Textual shells over :class:`~chess_coach.interface.tui.board_state.BoardState`
and the pure render helpers. A :class:`Square` is one clickable cell that reports
its coordinate; :class:`BoardWidget` lays 64 of them into a grid, redraws them from
the board, and rebuilds them when the view is flipped. No chess or coaching logic
lives here — the app routes clicks to the model and asks the widget to redraw.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.containers import Grid
from textual.message import Message
from textual.widgets import Static

from chess_coach.interface.tui import rendering
from chess_coach.interface.tui.board_state import BoardState


class Square(Static):
    """One clickable board cell; posts :class:`Square.Clicked` with its coordinate."""

    class Clicked(Message):
        def __init__(self, square: str) -> None:
            self.square = square
            super().__init__()

    def __init__(self, square: str) -> None:
        super().__init__("", id=f"sq-{square}")
        self.square = square

    def on_click(self) -> None:
        self.post_message(self.Clicked(self.square))


class CoordinateLabel(Static):
    """A non-clickable board coordinate label."""

    def __init__(self, text: str, *, id: str) -> None:  # noqa: A002 - Textual uses id
        super().__init__(text, id=id, classes="coordinate-label")


class BoardWidget(Grid):
    """An 8x8 grid of :class:`Square`s drawn from a :class:`BoardState`."""

    def __init__(self, board: BoardState) -> None:
        super().__init__(id="board")
        self._board = board

    def compose(self) -> Iterable[Static]:
        yield from self._cells()

    def redraw(self, selected: str | None = None) -> None:
        """Repaint every cell from the model, highlighting ``selected``."""
        for square in self._flat():
            cell = self.query_one(f"#sq-{square}", Square)
            symbol = self._board.piece_symbol_at(square)
            white = symbol is not None and rendering.piece_is_white(symbol)
            light = rendering.square_is_light(square)
            cell.update(rendering.board_piece_glyph(symbol))
            cell.set_class(light, "light")
            cell.set_class(not light, "dark")
            cell.set_class(square == selected, "selected")
            cell.set_class(white, "white")
            cell.set_class(symbol is not None and not white, "black")

    async def relayout(self) -> None:
        """Rebuild the grid after an orientation change, then repaint."""
        await self.remove_children()
        await self.mount_all(self._cells())
        self.redraw()

    def _flat(self) -> list[str]:
        rows = rendering.ordered_rows(self._board.orientation)
        return [square for row in rows for square in row]

    def _cells(self) -> list[Static]:
        rows = rendering.ordered_rows(self._board.orientation)
        ranks = rendering.rank_labels(self._board.orientation)
        files = rendering.file_labels(self._board.orientation)
        cells: list[Static] = []
        for index, row in enumerate(rows):
            cells.append(CoordinateLabel(ranks[index], id=f"rank-label-{index}"))
            cells.extend(Square(square) for square in row)
        cells.append(CoordinateLabel("", id="corner-label"))
        cells.extend(
            CoordinateLabel(file, id=f"file-label-{index}")
            for index, file in enumerate(files)
        )
        return cells

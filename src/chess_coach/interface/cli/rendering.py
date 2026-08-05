"""Terminal rendering: turn view data into formatted text.

The low-level drawing primitives for the CLI, kept out of the command and
presenter modules so the tool has one consistent look. Pure formatting: it accepts
already-prepared view data and returns strings, unaware of use cases or ports.

Tracing-bullet slice: the board diagram and a labelled-field line. The eval bar,
move tables and progress reports join here as their commands land.
"""

from __future__ import annotations

import chess


def board_diagram(fen: str) -> str:
    """Render ``fen`` as an 8x8 ASCII board with rank/file coordinates.

    Falls back to the raw FEN if it cannot be parsed, so rendering never raises on
    behalf of a caller that already validated (or chose not to).
    """
    try:
        board = chess.Board(fen)
    except ValueError:
        return fen
    rows = str(board).splitlines()
    ranks = range(8, 0, -1)
    body = "\n".join(f"{rank}  {row}" for rank, row in zip(ranks, rows, strict=False))
    return f"{body}\n\n   a b c d e f g h"


def field_line(label: str, value: str) -> str:
    """A single ``Label: value`` line with the label padded to a common width."""
    return f"{label + ':':<12} {value}"

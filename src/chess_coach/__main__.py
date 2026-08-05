"""Executable module entry point: ``python -m chess_coach``.

Thin launcher that hands control to the CLI application defined in
interface.cli.app, so ``python -m chess_coach`` and the installed ``chess-coach``
console-script behave identically.
"""

from __future__ import annotations

from chess_coach.interface.cli.app import main

if __name__ == "__main__":
    main()

"""chess-coach: an agentic chess coaching application.

A selected coach provider (the coaching brain) works with Stockfish (the source
of chess truth, exposed as a CLI/skill) to review games, track a player's
progress and run training drills, all delivered through a command-line interface.

Architecture (clean architecture; dependencies point inward):
    domain        — pure chess-coaching model (entities, value objects, errors).
    application   — use cases and the ports (interfaces) they depend on.
    adapters      — concrete implementations of the ports (Stockfish, coach
                    providers, PGN/Lichess/Chess.com sources, SQLite).
    interface     — delivery mechanisms (the CLI).
    composition   — the composition root that wires everything together.

Public surface:
    Exposes the package version. Application behaviour is reached through the CLI
    (`python -m chess_coach` / the `chess-coach` console-script), never by
    importing internals across layer boundaries.
"""

__version__ = "0.1.0"

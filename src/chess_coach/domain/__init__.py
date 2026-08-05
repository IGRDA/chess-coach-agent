"""Domain layer: enterprise business rules for chess coaching.

The innermost layer of the architecture. It contains the vocabulary of the
problem — positions, moves, games, evaluations, players, weaknesses, drills and
lessons — expressed as pure Python value objects and entities.

Dependency rule
    This package depends on *nothing* outside the standard library. It knows
    nothing about Stockfish, the Claude Agent SDK, HTTP APIs, SQLite or the CLI.
    Every outer layer may import from here; this layer imports from no other
    layer.

Public surface
    Re-exports the domain types that use cases and adapters are allowed to name
    (ids, Position, Move, Game, Evaluation, MoveAnnotation, Weakness, Drill,
    Player, Lesson, and the domain error hierarchy).
"""

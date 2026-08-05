"""Game entity: a complete chess game with identity and history.

Aggregates an ordered sequence of moves starting from an initial Position, plus
descriptive metadata (players, result, event, site, date, time control, source).
The central aggregate that analysis is performed over.

Exposes
    Game — an entity identified by GameId. Offers ordered traversal of its moves
    and the succession of Positions they produce, plus access to its metadata and
    final result. Provides the ability to reconstruct the position after any ply.

Collaborators
    Built by the game-source adapters (PGN / online); persisted via
    GameRepository; consumed by the AnalyzeGame use case.

Invariants
    Identity is the GameId, not the move list — two Games with identical moves are
    still distinct games. The move sequence is always legal from the starting
    position.
"""

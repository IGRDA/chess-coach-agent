"""Position value object: an immutable chess board state.

Represents a single legal position, backed by its FEN description, together with
the side to move and enough context to enumerate legal moves. This is the atomic
unit the engine evaluates and the coach explains.

Exposes
    Position — an immutable value object carrying the board state, side to move,
    move number and castling/en-passant rights. Offers read-only queries needed
    by the domain (side to move, whether the game is over, the set of legal
    moves) without exposing any third-party board representation.

Collaborators
    Consumed by Game (as its move-by-move states), Evaluation (the position that
    was scored) and Drill (the puzzle's starting position).

Invariants
    A Position instance is always legal and reachable; illegal FENs are rejected
    at construction and surfaced as a domain error (see errors.py). Instances are
    immutable — applying a move yields a new Position.
"""

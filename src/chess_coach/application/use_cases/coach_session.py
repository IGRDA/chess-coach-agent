"""CoachSession use case: interactive live play with running commentary.

Orchestrates a turn-by-turn game between the player and the coach. For each player
move it consults the engine for the objective assessment and best continuation,
asks the coach to comment at the player's level, optionally makes the coach's
reply move, and continues until the game ends — capturing notable moments as
Weaknesses for later practice.

Exposes
    CoachSession — a use case that steps a live game forward one player move at a
    time, returning per-move feedback DTOs, and yields a final review when the
    game concludes.

Depends on (ports)
    EnginePort, CoachPort, ProgressRepository (to persist what the session
    reveals).

Contract
    The use case holds no I/O of its own; the delivery layer supplies moves and
    renders feedback, keeping the interaction loop testable.
"""

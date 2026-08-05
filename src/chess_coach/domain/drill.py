"""Drill and DrillAttempt: a training exercise and a player's attempt at it.

A Drill is a targeted practice item — most often a tactics puzzle — consisting of
a starting Position, a stated objective, the correct solution line, motif tags
that link it to Weakness categories, and a difficulty rating. A DrillAttempt
records one player's response and whether it succeeded.

Exposes
    Drill — an entity identified by DrillId, exposing its Position, objective,
    solution line, motif tags and difficulty.
    DrillAttempt — an immutable record of a single attempt: which player, which
    moves were tried, success/failure, and time taken.

Collaborators
    Selected by RecommendDrills to match a player's Weaknesses; presented and
    graded by RunDrillSession; persisted via DrillRepository.

Invariants
    A Drill's solution line is legal from its starting Position. A DrillAttempt is
    immutable once recorded.
"""

"""Weakness value object: a recurring flaw in a player's play.

Represents an identified area for improvement — a tactical motif repeatedly
missed, a shaky opening, a mishandled endgame type — together with a measure of
severity and the evidence (references to the games and moves) that supports it.

Exposes
    Weakness — an immutable value object carrying a category, a severity measure,
    and supporting evidence references.
    Weakness category vocabulary — the taxonomy of improvement areas (tactical
    motifs, opening problems, endgame technique, time management, etc.).

Collaborators
    Derived by the AnalyzeGame / TrackProgress use cases from MoveAnnotations;
    stored on Player; consumed by RecommendDrills to target practice.

Invariants
    Immutable. Evidence references point at persisted games/moves, never embedded
    copies of them.
"""

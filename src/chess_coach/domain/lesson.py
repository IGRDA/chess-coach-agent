"""Lesson value object: a unit of natural-language coaching content.

Represents a piece of teaching produced by the coach — an explanation of a
position, a game summary, or a themed lesson addressing a Weakness — bound to the
concrete artefact it refers to (a game, a position, or a weakness) so it can be
shown alongside that context.

Exposes
    Lesson — an immutable value object carrying a title, the coaching prose, and a
    typed reference to what it teaches about.

Collaborators
    Produced through the CoachPort by the AnalyzePosition / AnalyzeGame /
    CoachSession use cases; rendered by the CLI presenters.

Invariants
    Immutable. Always anchored to exactly one subject (game, position or
    weakness).
"""

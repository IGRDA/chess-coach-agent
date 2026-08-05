"""Evaluation value object: an engine's judgement of a position.

Represents the result of analysing a Position: a score expressed either as a
centipawn advantage or a forced-mate distance, the search depth reached, and the
principal variation (the engine's expected best line).

Exposes
    Evaluation — an immutable value object carrying the score, depth and
    principal variation, with a normalised, side-to-move-relative reading of who
    stands better and by how much.
    Move-quality classification contract — the thresholds and vocabulary
    (blunder / mistake / inaccuracy / good / best) used to grade the swing in
    evaluation caused by a move. The concrete comparison is used by
    MoveAnnotation.

Collaborators
    Produced through the EnginePort; attached to moves by MoveAnnotation;
    summarised by the AnalyzeGame use case.

Invariants
    A mate score and a centipawn score are mutually exclusive. Evaluations are
    immutable and always interpreted relative to the side to move.
"""

"""MoveAnnotation value object: the coached verdict on a single move.

Binds together, for one ply of a game, the move played, the evaluation before and
after it, the resulting evaluation swing, the quality classification derived from
that swing, the engine's preferred alternative, and an optional natural-language
coach comment.

Exposes
    MoveAnnotation — an immutable record connecting a Move to its Evaluation
    delta, its quality classification (blunder / mistake / inaccuracy / good /
    best), the suggested better move, and the coach's explanation.

Collaborators
    Produced by the AnalyzeGame use case from Evaluation deltas; rendered by the
    CLI presenters; feeds Weakness detection.

Invariants
    Immutable. The classification is a pure function of the evaluation swing and
    the shared thresholds defined in evaluation.py.
"""

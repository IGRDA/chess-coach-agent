"""Move value object: a single played or candidate chess move.

Captures one move in both human (SAN) and machine (UCI) notation, along with its
origin and destination squares, the moving piece and its flags (capture, check,
checkmate, promotion, castling, en passant).

Exposes
    Move — an immutable value object describing a move independently of the board
    library used to generate it.

Collaborators
    Sequenced by Game; scored via Evaluation; judged by MoveAnnotation; forms the
    solution line of a Drill.

Invariants
    A Move is immutable and only meaningful relative to the Position it was made
    in; it carries no board state of its own.
"""

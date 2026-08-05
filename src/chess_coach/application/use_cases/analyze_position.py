"""AnalyzePosition use case: assess and explain a single position.

Takes a position (as a FEN), has the engine evaluate it, and asks the coach to
turn that evaluation into a human explanation pitched at the player's level. This
is the FEN-oriented, one-shot analysis entry point used by both the CLI and the
agent.

Exposes
    AnalyzePosition — invoked with a request DTO (the FEN, optional search limits,
    audience level); returns a result DTO pairing the Evaluation with a coaching
    Lesson.

Depends on (ports)
    PositionParserPort, EnginePort, CoachPort.

Contract
    An illegal FEN is rejected as a domain error before any engine work is done.
"""

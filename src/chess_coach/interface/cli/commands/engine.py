"""`engine` command: Stockfish as an agent-callable tool.

Exposes the engine directly on the command line — given a FEN (and optional search
limits) it returns the evaluation and best move in a compact, machine-readable
form. This is the surface the Claude coach agent invokes as a tool/skill to
consult Stockfish, and it doubles as a debugging aid for humans.

Drives (ports)
    EnginePort (via PositionParserPort for the FEN).

Collaborators
    Kept deliberately thin and stable so the agent skills in `skills/` can depend
    on its input/output contract; renders results in a script-friendly format.
"""

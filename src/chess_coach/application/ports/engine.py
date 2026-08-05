"""EnginePort: the boundary to a chess engine.

A deep, narrow contract for obtaining objective chess judgements. The interface is
small — evaluate a position, find the best move(s), analyse a whole game — while
implementations hide the entire complexity of the UCI protocol, engine process
management and search-limit tuning.

Exposes
    EnginePort — a protocol offering: evaluate a Position under given search
    limits, returning an Evaluation; produce the best move for a Position; and
    analyse a Game ply-by-ply into a sequence of Evaluations.
    Search-limit specification — how callers express "how hard to think" (by
    depth, node count or time) without referencing any engine internals.

Collaborators
    Depended on by AnalyzePosition, AnalyzeGame and CoachSession. Implemented by
    the Stockfish adapter and by test fakes.

Contract
    Deterministic given the same position and limits (subject to the engine's own
    determinism). Never exposes a third-party engine handle across the boundary.
"""

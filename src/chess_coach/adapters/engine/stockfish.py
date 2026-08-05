"""Stockfish adapter: EnginePort backed by a Stockfish UCI process.

Implements EnginePort by driving a Stockfish binary over the UCI protocol. This is
a deep module: its interface is the three EnginePort operations, while it hides
process spawning and shutdown, UCI option configuration, translation of the
application's search-limit specification into engine limits, and conversion of raw
engine output into domain Evaluation / Move objects.

Implements
    EnginePort.

Collaborators
    Configured with the Stockfish binary path and default options by the
    composition root. Used by the analysis and coaching use cases and exposed to
    the agent through the `engine` CLI command.

Hidden complexity
    The UCI handshake, engine process lifecycle, thread/hash configuration, and
    the mapping between position/limits and the engine's own representation never
    escape this module.
"""

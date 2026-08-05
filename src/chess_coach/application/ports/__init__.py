"""Ports: the abstract boundaries between the application and the outside world.

Each port is a narrow protocol (an interface) stated purely in domain terms.
Adapters in the outer layer implement these protocols; the composition root
injects the implementations. This is the dependency-inversion seam that keeps the
use cases ignorant of Stockfish, the Claude Agent SDK, HTTP and SQLite.

Public surface
    Re-exports the port protocols: EnginePort, CoachPort, GameSourcePort,
    PositionParserPort, the repository ports and ClockPort.
"""

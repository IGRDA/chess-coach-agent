"""Adapters layer: concrete implementations of the application's ports.

The outer ring on the technology side. Each subpackage here implements one or more
ports declared in application.ports, translating between the domain's vocabulary
and a specific external technology — Stockfish (UCI), the Claude Agent SDK, HTTP
chess APIs, and SQLite storage.

Dependency rule
    Depends inward on the application and domain layers; nothing in those layers
    ever imports from here. Adapters are selected and instantiated only by the
    composition root.
"""

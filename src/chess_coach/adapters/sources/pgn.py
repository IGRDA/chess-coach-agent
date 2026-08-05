"""PGN source adapter: GameSourcePort backed by PGN files.

Implements GameSourcePort by reading one or many games from PGN text/files and
mapping each into a domain Game (moves, starting position and metadata). Hides all
PGN tokenising and header parsing.

Implements
    GameSourcePort.

Collaborators
    Selected by the composition root for the `import pgn` path and whenever the
    CLI is handed a PGN.

Hidden complexity
    PGN grammar quirks, variations/comments handling and header normalisation stay
    inside this module; malformed PGN becomes a domain error.
"""

"""GameSourcePort and PositionParserPort: boundaries to inbound chess data.

Abstracts where games and positions come from, so the use cases treat a PGN file,
a Lichess account, a Chess.com account and a pasted FEN uniformly.

Exposes
    GameSourcePort — a protocol for importing Games from some source, yielding a
    stream of domain Game objects regardless of the underlying format or API.
    PositionParserPort — a protocol for turning a single FEN string into a domain
    Position.

Collaborators
    Depended on by ImportGames (GameSourcePort) and by the analysis/coach use
    cases that accept a FEN (PositionParserPort). Implemented by the PGN, Lichess,
    Chess.com and FEN adapters, and by test fakes.

Contract
    Sources translate all external/format errors into domain errors at the
    boundary; callers only ever see valid domain objects or a domain error.
"""

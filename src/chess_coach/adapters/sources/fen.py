"""FEN source adapter: PositionParserPort backed by FEN strings.

Implements PositionParserPort by validating a FEN string and constructing the
corresponding domain Position. Hides FEN field parsing and legality checking.

Implements
    PositionParserPort.

Collaborators
    Used by every use case that accepts a raw position (AnalyzePosition, drill
    authoring, the `engine` CLI command).

Hidden complexity
    FEN syntax and legality validation stay inside this module; an invalid FEN
    becomes a domain error before any Position is produced.
"""

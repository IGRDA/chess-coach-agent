"""ImportGames use case: bring external games into the system.

Reads Games from a chosen GameSourcePort (a PGN file, a Lichess account, a
Chess.com account) and persists them through the GameRepository, so they become
available for analysis and progress tracking.

Exposes
    ImportGames — invoked with an import request DTO (which source, which
    account/file, optional filters); returns a result DTO summarising how many
    games were imported and their identifiers.

Depends on (ports)
    GameSourcePort, GameRepository.

Contract
    Idempotent with respect to already-imported games where the source provides
    stable identifiers; malformed input surfaces as a domain error rather than a
    partial import.
"""

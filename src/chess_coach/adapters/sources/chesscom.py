"""Chess.com source adapter: GameSourcePort backed by the Chess.com API.

Implements GameSourcePort by fetching a user's monthly game archives from the
Chess.com public API and mapping them into domain Games. Hides HTTP transport,
archive discovery and the response format.

Implements
    GameSourcePort.

Collaborators
    Configured with an HTTP client by the composition root; selected for the
    `import chesscom` path.

Hidden complexity
    Archive-index traversal, pagination and API-specific error handling stay
    inside this module; the use cases see only domain Games or a domain error.
"""

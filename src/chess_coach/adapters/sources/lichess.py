"""Lichess source adapter: GameSourcePort backed by the Lichess API.

Implements GameSourcePort by fetching a user's games from the Lichess HTTP API and
mapping them into domain Games. Hides HTTP transport, authentication, pagination,
rate limiting and the export format.

Implements
    GameSourcePort.

Collaborators
    Configured with an optional API token and HTTP client by the composition
    root; selected for the `import lichess` path.

Hidden complexity
    All networking, streaming/NDJSON parsing and API-specific error handling stay
    inside this module; the use cases see only domain Games or a domain error.
"""

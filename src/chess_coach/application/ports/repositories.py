"""Repository ports: boundaries to persistence, stated in domain terms.

Collision-free contracts for storing and retrieving the aggregates, exposing only
the queries the use cases actually need — no SQL, no ORM, no storage vocabulary
leaks across the boundary.

Exposes
    GameRepository — save and load Games by GameId, and list a player's games.
    ProgressRepository — save and load Players (profile, rating, weaknesses,
    history) by PlayerId.
    DrillRepository — save and load Drills and DrillAttempts, and query Drills by
    motif/difficulty for recommendation.

Collaborators
    Depended on by every use case that reads or writes state. Implemented by the
    SQLite adapters and by in-memory fakes in tests.

Contract
    Persistence is expressed as whole-aggregate save/load. A missing entity is a
    defined outcome (surfaced as a domain error or an explicit "not found"),
    never an undefined state.
"""

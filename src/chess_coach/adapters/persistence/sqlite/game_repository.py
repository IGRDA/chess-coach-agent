"""SQLite GameRepository: persistence of Games.

Implements the GameRepository port against SQLite, saving and loading whole Game
aggregates (moves, starting position and metadata) and listing a player's games.
Hides all SQL and row/aggregate translation (via mappers.py).

Implements
    GameRepository.

Collaborators
    Constructed with a database connection/handle by the composition root; uses
    mappers.py for translation and the schema from schema.py.

Hidden complexity
    SQL statements, transactions and connection handling stay inside this module.
"""

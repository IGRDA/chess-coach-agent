"""SQLite schema and migrations.

Defines the database tables backing the repositories (games and their moves,
players and their weaknesses, drills and drill attempts) and the forward
migrations that bring a database up to the current version. Centralising the
schema keeps the repository modules focused on queries.

Exposes
    The table/migration definitions and a way to initialise or upgrade a database
    to the current schema version.

Collaborators
    Applied at startup by the composition root; the schema it defines is assumed
    by the SQLite repositories and mappers.
"""

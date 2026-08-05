"""SQLite persistence: repository ports backed by a local SQLite database.

Bundles the schema/migrations and the three SQLite repository implementations.
SQLite is chosen for a local, zero-operations coaching tool; because the use cases
depend only on the repository ports, this backend can be swapped for another
without changing the application layer.
"""

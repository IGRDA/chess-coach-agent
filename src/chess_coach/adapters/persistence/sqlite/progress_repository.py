"""SQLite ProgressRepository: persistence of Player profiles.

Implements the ProgressRepository port against SQLite, saving and loading whole
Player aggregates — rating estimate, known weaknesses and history references.
Hides all SQL and row/aggregate translation.

Implements
    ProgressRepository.

Collaborators
    Constructed with a database connection/handle by the composition root; uses
    mappers.py and the schema from schema.py.

Hidden complexity
    SQL statements, transactions and connection handling stay inside this module.
"""

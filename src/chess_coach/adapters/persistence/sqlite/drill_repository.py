"""SQLite DrillRepository: persistence of Drills and DrillAttempts.

Implements the DrillRepository port against SQLite: storing and loading Drills and
their attempts, and querying the drill pool by motif and difficulty for
recommendation. Hides all SQL and row/aggregate translation.

Implements
    DrillRepository.

Collaborators
    Constructed with a database connection/handle by the composition root; uses
    mappers.py and the schema from schema.py; queried by RecommendDrills.

Hidden complexity
    SQL statements, indexing/filtering and connection handling stay inside this
    module.
"""

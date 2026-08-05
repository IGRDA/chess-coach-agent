"""Domain <-> storage row mapping.

Central place that converts domain aggregates (Game, Player, Drill, DrillAttempt)
to and from their persisted row/record form. Keeping this translation in one
module means the SQL repositories deal in rows while the domain deals in
aggregates, and neither leaks into the other.

Exposes
    Bidirectional mapping operations for each persisted aggregate.

Collaborators
    Used exclusively by the SQLite repositories.

Note
    Pure translation — no I/O and no business rules.
"""

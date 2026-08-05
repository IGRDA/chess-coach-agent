"""ClockPort: the boundary to the current time.

Abstracts "now" so that time-dependent logic — chiefly spaced-repetition
scheduling of drills — is deterministic and testable. Use cases ask the clock
rather than reading the system time directly.

Exposes
    ClockPort — a protocol returning the current instant.

Collaborators
    Depended on by RecommendDrills and RunDrillSession (scheduling) and by
    TrackProgress (timestamping). Implemented by a real system-clock adapter and
    by a fixed-time fake in tests.

Contract
    The only source of wall-clock time in the application layer, enabling
    reproducible tests.
"""

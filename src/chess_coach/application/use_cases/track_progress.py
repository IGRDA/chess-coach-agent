"""TrackProgress use case: maintain and report a player's development.

Owns the read and update paths for a Player's profile: folding newly detected
Weaknesses and drill outcomes into the profile, revising the rating estimate over
time, and producing a progress report on demand.

Exposes
    TrackProgress — offers updating a profile from new evidence (weaknesses,
    attempts, results) and querying a progress report DTO (current rating trend,
    active weaknesses, recent activity) for a player.

Depends on (ports)
    ProgressRepository, ClockPort.

Contract
    All profile changes go through the Player entity's own operations so the
    profile stays internally consistent; every change is timestamped via the
    clock.
"""

"""Player entity: the coached user and their evolving profile.

Models the person being coached: a stable identity, an estimated playing
strength, the set of known Weaknesses, and references to their analysis and drill
history. This is the aggregate that progress tracking reads and updates.

Exposes
    Player — an entity identified by PlayerId, exposing the current rating
    estimate, the known Weaknesses, and history references. Offers the domain
    operations that keep the profile consistent as new evidence arrives (revise
    rating, record/retire a weakness).

Collaborators
    Persisted via ProgressRepository; updated by TrackProgress and
    RunDrillSession; read by RecommendDrills and the coach.

Invariants
    Identity is the PlayerId. Rating and weaknesses are only ever changed through
    the entity's own operations, keeping the profile internally consistent.
"""

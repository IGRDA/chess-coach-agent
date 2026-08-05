"""RecommendDrills use case: choose what the player should practise next.

Reads a Player's active Weaknesses and drill history and selects a set of Drills
that target those weaknesses, ordered by a spaced-repetition schedule so that due
and high-severity material surfaces first. Optionally asks the coach to explain
why each drill was chosen.

Exposes
    RecommendDrills — invoked with a request DTO (which player, how many drills);
    returns a result DTO listing the chosen Drills with their rationale.

Depends on (ports)
    ProgressRepository, DrillRepository, ClockPort, CoachPort (for rationale).

Contract
    Selection is deterministic given the same profile, drill pool and clock
    reading, making recommendations reproducible and testable.
"""

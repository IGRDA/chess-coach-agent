"""RunDrillSession use case: present a drill, grade it, and record the result.

Drives one practice interaction: it serves a Drill's starting position and
objective, receives the player's attempted line, grades it against the solution
(optionally consulting the engine for near-miss credit), records the DrillAttempt,
and updates the player's progress and spaced-repetition schedule accordingly.

Exposes
    RunDrillSession — invoked with a request DTO (which player, which drill, the
    attempted moves); returns a result DTO with the grading outcome, the correct
    line, and any coach feedback.

Depends on (ports)
    DrillRepository, ProgressRepository, ClockPort, EnginePort (grading),
    CoachPort (feedback).

Contract
    A DrillAttempt is always recorded, whether the attempt succeeded or failed,
    so progress reflects effort as well as outcome.
"""

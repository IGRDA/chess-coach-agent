"""AnalyzeGame use case: full-game review and weakness capture.

Loads a Game, has the engine evaluate every ply, derives a MoveAnnotation for each
move (classifying blunders, mistakes and inaccuracies from the evaluation swings),
asks the coach for a game summary Lesson, extracts the recurring Weaknesses the
game reveals, and feeds those into the player's profile via progress tracking.

Exposes
    AnalyzeGame — invoked with a request DTO (which GameId or freshly parsed game,
    which player, search limits); returns a result DTO with the annotated game,
    the summary Lesson and the detected Weaknesses.

Depends on (ports)
    GameRepository, EnginePort, CoachPort, ProgressRepository.

Contract
    Analysis is read-only with respect to the Game; the only state it mutates is
    the player's progress, and only after the full analysis succeeds.
"""

"""`drill` command: get recommended drills and run practice sessions.

Parses the drill verb and its mode — recommend (list drills targeting the player's
weaknesses) or run (attempt a specific drill and be graded) — dispatching to the
matching use case and rendering the recommendations or the graded outcome.

Drives (use cases)
    RecommendDrills, RunDrillSession.

Collaborators
    Builds request DTOs from argv; for `run`, reads the attempted line from the
    terminal; renders via presenters.py.
"""

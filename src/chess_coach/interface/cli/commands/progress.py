"""`progress` command: view a player's development.

Parses the progress verb (which player), invokes TrackProgress to obtain the
progress report, and renders the rating trend, active weaknesses and recent
activity.

Drives (use cases)
    TrackProgress.

Collaborators
    Builds the request DTO from argv; renders the report via presenters.py.
"""

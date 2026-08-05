"""`analyze` command: review a game or assess a position.

Parses the analyze verb (a stored GameId, a PGN path, or a FEN, plus options such
as search depth and audience level), routes to AnalyzeGame or AnalyzePosition
accordingly, and renders the annotated review or position assessment.

Drives (use cases)
    AnalyzeGame, AnalyzePosition.

Collaborators
    Builds request DTOs from argv; renders results via presenters.py.
"""

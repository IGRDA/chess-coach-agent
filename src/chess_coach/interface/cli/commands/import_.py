"""`import` command: bring games in from a source.

Parses the import verb and its source (a PGN path, or a Lichess/Chess.com
username), builds the import request, invokes ImportGames, and reports how many
games were imported. Named with a trailing underscore to avoid shadowing the
`import` keyword.

Drives (use cases)
    ImportGames.

Collaborators
    Builds request DTOs from argv; renders the summary via presenters.py.
"""

"""Offline, human-run tooling for building and checking the dataset.

These are scripts, not part of the pytest run: :mod:`evals.tools.extract_problems`
turns curated book pages into goldens via a vision model, and
:mod:`evals.tools.validate_goldens` re-proves every committed golden against
python-chess and Stockfish. :mod:`evals.tools.report` summarises a run's scores.
"""

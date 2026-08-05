"""Domain error taxonomy.

Defines the hierarchy of errors that express violations of domain rules in the
problem's own vocabulary, so that outer layers can translate them into exit codes
or messages without leaking library-specific exceptions inward. Every domain
error derives from :class:`CoachError`, so the interface layer can catch the whole
family uniformly and map it to an exit code.

This is the tracing-bullet slice: the two errors the coach-a-position path can
actually raise. Further specialisations (unknown player, unknown drill, malformed
game) join here as their use cases land.
"""

from __future__ import annotations


class CoachError(Exception):
    """Base type for every error expressed in the domain's own vocabulary."""


class InvalidPositionError(CoachError):
    """The supplied FEN is not a legal, reachable chess position."""


class UnknownTaskError(CoachError):
    """The requested coaching task is not one the coach knows how to perform."""

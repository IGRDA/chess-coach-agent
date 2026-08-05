"""Typed identifiers for domain entities.

Provides distinct value-object identifier types — GameId, PlayerId, DrillId,
AnalysisId — so that identities cannot be silently confused with each other or
with bare strings. Each identifier is immutable, equality-comparable and
hashable so it can key dictionaries and repository lookups.

Exposes
    GameId, PlayerId, DrillId, AnalysisId — opaque, self-validating identifier
    value objects, plus a way to mint a fresh identifier.

Invariants
    An identifier, once constructed, never changes. Two identifiers of different
    types are never equal even if their underlying representation matches.
"""

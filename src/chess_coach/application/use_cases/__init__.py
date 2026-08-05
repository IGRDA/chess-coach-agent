"""Use cases: the coaching workflows the system offers.

Each module here is a single deep use case — one orchestration of domain objects
and ports that fulfils a complete user or agent intent. Use cases are the only
things the delivery layer calls; they are the application's public verbs.

Public surface
    Re-exports the use-case entry points: ImportGames, AnalyzePosition,
    AnalyzeGame, TrackProgress, RecommendDrills, RunDrillSession, CoachSession.
"""

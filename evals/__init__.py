"""Evaluation framework for the chess-coach agent.

A standalone tree (not shipped in the ``chess_coach`` package) that grades a
coach through a pluggable task boundary. Positions come from a curated,
vision-extracted selection of chess-book problems; ground truth comes from
Stockfish and python-chess. Deterministic exact-match/structured metrics run by
default (local, network-free); an LLM-as-judge metric is opt-in behind the
``judge`` pytest marker.
"""

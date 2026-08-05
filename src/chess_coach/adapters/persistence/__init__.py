"""Persistence adapters: implementations of the repository ports.

Concrete storage integrations plus the mapping between domain aggregates and their
stored representation. The default backend is SQLite (see the `sqlite` subpackage);
mappers.py isolates the domain<->row translation so the rest of the code never
sees storage shapes.
"""

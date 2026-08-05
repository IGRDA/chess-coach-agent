"""The golden dataset: schema, loader, and the committed problem files.

A *golden* is one graded chess problem — a position, what to ask, and the
ground-truth answer — validated at authoring time by python-chess and Stockfish.
:mod:`evals.data.schema` defines the record; :mod:`evals.data.loader` reads the
``goldens/*.json`` files into validated records and into deepeval test cases.
"""

from evals.data.schema import ChessGolden, Extraction

__all__ = ["ChessGolden", "Extraction"]

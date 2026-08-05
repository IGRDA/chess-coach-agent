"""CLI command modules: one module per user-facing verb.

Each module defines a single sub-command that parses that verb's arguments, builds
the corresponding use-case request DTO, invokes the use case, and hands the result
to a presenter. Commands hold no coaching logic; they are the thin translation
between argv and the application layer.
"""

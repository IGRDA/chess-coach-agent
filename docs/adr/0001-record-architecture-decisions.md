# 1. Record architecture decisions

Date: 2026-07-12

## Status

Accepted

## Context

`chess-coach` is starting from a skeleton and will grow feature by feature. The
foundational choices — clean architecture with ports & adapters, Stockfish as an
agent-invoked CLI tool, Claude as the coaching brain behind a port, SQLite for
local persistence, and a CLI as the first delivery mechanism — need to be recorded
so that future contributors (human and agent) understand *why* the structure is
what it is, not just *what* it is.

## Decision

We will use Architecture Decision Records (ADRs), one Markdown file per decision,
numbered sequentially in `docs/adr/`. Each records the context, the decision and
its consequences. This document is the first such record and establishes the
practice; the initial structural decisions are captured in `docs/architecture.md`
and will be split into their own ADRs as they are revisited.

## Consequences

- Every significant, hard-to-reverse decision gets a short, durable rationale.
- Superseded decisions are kept (marked *Superseded by NNNN*) rather than deleted,
  preserving the history of the design.
- New ADRs follow this template.

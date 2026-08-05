"""Application layer: use cases and the ports they depend on.

Encodes the application-specific business rules — the coaching workflows a user
or the agent can invoke — and declares the abstract boundaries (ports) through
which those workflows reach the outside world.

Dependency rule
    Depends only on the domain layer. It never imports adapters, the CLI, or any
    third-party framework. Concrete implementations of its ports are supplied
    from the composition root.

Public surface
    Re-exports the use-case entry points and the port protocols that the
    composition root wires together.
"""

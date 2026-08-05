"""Composition root: where the whole application is assembled.

The single place that is allowed to know every concrete type. It reads
configuration, instantiates the adapters (engine, coach, sources, repositories),
injects them into the use cases, and hands the fully-wired services to the
delivery layer. Because all wiring lives here, every other module can stay
decoupled and depend only on ports.

Contents
    config.py — how configuration is sourced and validated.
    container.py — how adapters are built and injected into use cases.
"""

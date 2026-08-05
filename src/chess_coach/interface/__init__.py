"""Interface layer: delivery mechanisms that drive the use cases.

The outer ring on the delivery side. Today it hosts the command-line interface;
other front-ends (an HTTP API, a bot) could live here later. Delivery code is kept
thin — it translates external input into use-case requests and renders the
results — so that no business logic leaks out of the application layer.

Dependency rule
    Depends inward on the application and domain layers; it is invoked by the
    composition root, which supplies it fully-wired use cases.
"""

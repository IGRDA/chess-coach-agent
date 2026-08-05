"""Where the Phoenix server lives, and a client for it.

One place resolves the endpoint (``PHOENIX_COLLECTOR_ENDPOINT``, defaulting to the
local ``phoenix serve`` UI) so ``upload`` and ``run`` agree. The client import is local
so merely importing the eval package never requires the Phoenix client to be installed.
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_ENDPOINT = "http://localhost:6006"


def endpoint() -> str:
    """The Phoenix base URL (traces + datasets + experiments)."""
    return os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", DEFAULT_ENDPOINT)


def make_client() -> Any:
    """A Phoenix client pointed at :func:`endpoint`."""
    from phoenix.client import Client

    return Client(base_url=endpoint())

"""Optional headless-browser backends for the ladder's tier-2 rendering.

Nothing here imports a browser library at module load; each backend checks its
own dependency in ``available()``. ``load_default_browser_backend`` returns the
first backend whose extra is installed (nodriver preferred), or None.
"""
from __future__ import annotations

from .base import BrowserFetcher
from .camoufox_backend import CamoufoxFetcher
from .nodriver_backend import NodriverFetcher

__all__ = [
    "BrowserFetcher", "NodriverFetcher", "CamoufoxFetcher",
    "load_default_browser_backend",
]


def load_default_browser_backend() -> BrowserFetcher | None:
    for cls in (NodriverFetcher, CamoufoxFetcher):
        backend = cls()
        if backend.available():
            return backend
    return None

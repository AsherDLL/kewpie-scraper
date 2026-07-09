"""The Fetcher protocol shared by every ladder tier.

A tier is any object that can attempt a single fetch of a URL and report back
a ``FetchResult``. Tiers do not cache or apply the learned policy themselves;
the ``EscalatingFetcher`` orchestrates those concerns around them.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from ..engine.identity import Identity
from ..engine.proxies import ProxyConfig
from ..models import FetchResult


@runtime_checkable
class Fetcher(Protocol):
    name: str

    def available(self) -> bool:
        """Whether this tier can run (e.g. optional browser dep installed)."""
        ...

    def fetch(self, url: str, *,
              headers: Optional[dict] = None,
              identity: Optional[Identity] = None,
              proxy: Optional[ProxyConfig] = None,
              wait_for: Optional[str] = None) -> FetchResult:
        ...

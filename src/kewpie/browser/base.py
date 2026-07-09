"""Protocol for headless-browser backends (the ladder's tier-2 rendering)."""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from ..engine.identity import Identity
from ..engine.proxies import ProxyConfig
from ..models import FetchResult


@runtime_checkable
class BrowserFetcher(Protocol):
    name: str

    def available(self) -> bool:
        """Whether the backing library and a usable browser are present."""
        ...

    def fetch(self, url: str, *,
              headers: Optional[dict] = None,
              identity: Optional[Identity] = None,
              proxy: Optional[ProxyConfig] = None,
              wait_for: Optional[str] = None,
              timeout_s: float = 30.0) -> FetchResult:
        ...

    def close(self) -> None:
        ...

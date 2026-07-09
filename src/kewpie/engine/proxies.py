"""Optional proxy support with deterministic identity pairing.

Reads from an env var or explicit config. Beyond simple rotation, this
module can *pair* a proxy to a (host, identity) deterministically:
reusing one TLS fingerprint (JA4) across many IPs is itself a bot signal,
so binding an identity to a stable exit IP per host is stealthier than
spraying one fingerprint across the whole pool.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from random import choice
from typing import Sequence


@dataclass(frozen=True)
class ProxyConfig:
    """One proxy endpoint."""
    url: str          # e.g. "http://user:pass@proxy.example.com:8000"
    label: str = ""   # human-readable name for logging


class ProxyRotator:
    """Random / round-robin / deterministic proxy selection.

    An empty pool returns None (no proxy applied). The StealthClient
    passes whatever we return into curl_cffi's ``proxies`` parameter.
    """

    def __init__(self, proxies: Sequence[ProxyConfig] | None = None,
                 mode: str = "random"):
        self.proxies = list(proxies or [])
        if mode not in ("random", "round_robin"):
            raise ValueError("mode must be 'random' or 'round_robin'")
        self.mode = mode
        self._cursor = 0

    @classmethod
    def from_env(cls) -> "ProxyRotator":
        """Build from the SCRAPING_PROXY_URL env var (single proxy).

        For multi-proxy setups, pass an explicit list to __init__.
        """
        url = os.environ.get("SCRAPING_PROXY_URL")
        if not url:
            return cls(proxies=[])
        return cls(proxies=[ProxyConfig(url=url, label="env")])

    def pick(self) -> ProxyConfig | None:
        if not self.proxies:
            return None
        if self.mode == "random":
            return choice(self.proxies)
        # round_robin
        p = self.proxies[self._cursor % len(self.proxies)]
        self._cursor += 1
        return p

    def pick_for(self, host: str, identity_idx: int) -> ProxyConfig | None:
        """Deterministically bind a proxy to a (host, identity) pair.

        The same identity always exits through the same proxy for a given
        host, so we never present one TLS fingerprint from many IPs. With
        an empty pool this returns None (direct connection).
        """
        if not self.proxies:
            return None
        seed = f"{host}\n{identity_idx}".encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        idx = int.from_bytes(digest[:4], "big") % len(self.proxies)
        return self.proxies[idx]

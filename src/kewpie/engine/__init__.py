"""Kewpie HTTP impersonation engine (tiers 0-1 of the escalation ladder)."""
from __future__ import annotations

from .cache import CachedEntry, DiskCache
from .client import CachedResponse, CassetteMiss, StealthClient
from .identity import (
    DEFAULT_POOL, Identity, load_identity_map, pick_for_host, pick_for_url,
    save_identity_map,
)
from .proxies import ProxyConfig, ProxyRotator
from .rate_limit import PerHostRateLimiter
from .retry import RETRY_STATUSES, default_retryable, retry_with_backoff
from .session import homepage_url

__all__ = [
    "StealthClient", "CachedResponse", "CassetteMiss",
    "DiskCache", "CachedEntry",
    "Identity", "DEFAULT_POOL", "pick_for_host", "pick_for_url",
    "load_identity_map", "save_identity_map",
    "ProxyConfig", "ProxyRotator",
    "PerHostRateLimiter",
    "RETRY_STATUSES", "retry_with_backoff", "default_retryable",
    "homepage_url",
]

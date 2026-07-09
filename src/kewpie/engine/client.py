"""StealthClient: the impersonation HTTP client at the heart of the engine.

Combines:
- curl_cffi for TLS/JA3/JA4 fingerprint impersonation
- A rotating identity pool (modern Chrome + Firefox builds) so a fleet of
  hosts does not look like one client
- Per-host sticky identity (optionally persisted to disk) so cookies, ETags
  and bot-manager scoring survive across requests and across runs
- Coherent navigation headers (Sec-CH-UA, Sec-Fetch-*, Accept-Language)
  matched to the impersonated browser
- PerHostRateLimiter for ethical/safe pacing
- DiskCache for cheap re-runs, with a record/replay cassette mode
- ProxyRotator with deterministic identity->proxy pairing
- retry_with_backoff for transient failures
- classify_challenge-driven block detection with identity rotation on block

Usage:
    from kewpie import StealthClient
    client = StealthClient(cache_dir=".kewpie_state/cache")
    r = client.get("https://example.com")
    print(r.text)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

try:
    from curl_cffi import requests as cc_requests
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "curl_cffi is required for StealthClient. Install with "
        "`pip install curl_cffi`."
    ) from e

from ..challenge import classify_challenge
from .cache import DiskCache
from .identity import (
    DEFAULT_POOL, Identity, load_identity_map, pick_for_host, save_identity_map,
)
from .proxies import ProxyRotator
from .rate_limit import PerHostRateLimiter
from .retry import RETRY_STATUSES, retry_with_backoff
from .session import homepage_url

log = logging.getLogger(__name__)


class CassetteMiss(RuntimeError):
    """Raised when a replay-only cassette has no entry for a request."""


@dataclass
class CachedResponse:
    """Wrapped response with the same minimal surface as curl_cffi.Response."""
    text: str
    content: bytes
    status_code: int
    headers: dict
    url: str
    from_cache: bool

    def json(self) -> Any:
        import json
        return json.loads(self.text)


class StealthClient:
    """Reusable, anti-bot-detection-aware HTTP GET client.

    Defaults are conservative and ethical. Override only when you know your
    target's policies and have permission.
    """

    def __init__(
        self,
        rate_limit_per_second: float = 1.0,
        cache_dir: Path | str | None = None,
        cache_ttl_hours: float = 6.0,
        max_retries: int = 3,
        proxy_rotator: ProxyRotator | None = None,
        default_timeout_s: float = 30.0,
        warm_session: bool = False,
        identity_pool: tuple[Identity, ...] = DEFAULT_POOL,
        identity_state_path: Path | str | None = None,
        cassette_mode: str = "off",
        impersonate: str | None = None,  # legacy override; pins ALL hosts
    ):
        self.rate_limiter = PerHostRateLimiter(rate_limit_per_second)
        self.cache: DiskCache | None = (
            DiskCache(cache_dir, ttl_hours=cache_ttl_hours, mode=cassette_mode)
            if cache_dir else None
        )
        self.max_retries = max_retries
        self.proxy_rotator = proxy_rotator or ProxyRotator.from_env()
        self.timeout_s = default_timeout_s
        self.warm_session = warm_session
        self._warmed_hosts: set[str] = set()
        self.identity_pool = identity_pool
        # Legacy `impersonate=`: build a single-identity pool so every host
        # gets that target. Kept for API compatibility; new code should use the
        # coherent identity pool instead of an empty-UA pinned target.
        if impersonate is not None:
            self.identity_pool = (
                Identity(
                    name=f"legacy-{impersonate}",
                    impersonate=impersonate,
                    user_agent="",
                    accept_language="en-US,en;q=0.9",
                    sec_ch_ua="",
                    sec_ch_ua_full_version_list="",
                    sec_ch_ua_platform="",
                    sends_client_hints=False,
                ),
            )
        # Optional persistence of the per-host identity choice.
        self._identity_state_path = (
            Path(identity_state_path) if identity_state_path else None
        )
        self._host_identity_idx: dict[str, int] = (
            load_identity_map(self._identity_state_path)
            if self._identity_state_path else {}
        )
        # Per-host curl_cffi session, keyed by (host, identity index).
        self._sessions: dict[tuple[str, int], cc_requests.Session] = {}

    # ----- identity / session management -----

    def _identity_for(self, host: str) -> tuple[Identity, int]:
        if host not in self._host_identity_idx:
            chosen = pick_for_host(host, self.identity_pool)
            self._host_identity_idx[host] = self.identity_pool.index(chosen)
            self._persist_identities()
        idx = self._host_identity_idx[host]
        return self.identity_pool[idx], idx

    def _session_for(self, host: str, idx: int) -> "cc_requests.Session":
        key = (host, idx)
        s = self._sessions.get(key)
        if s is None:
            ident = self.identity_pool[idx]
            s = cc_requests.Session(impersonate=ident.impersonate)
            self._sessions[key] = s
        return s

    def _rotate_identity(self, host: str) -> None:
        """Advance the host's identity to the next pool entry (called when we
        suspect the previous one was block-scored)."""
        current = self._host_identity_idx.get(host, 0)
        self._host_identity_idx[host] = (current + 1) % len(self.identity_pool)
        self._persist_identities()
        log.info("rotated identity for %s -> %s", host,
                 self.identity_pool[self._host_identity_idx[host]].name)

    def _persist_identities(self) -> None:
        if self._identity_state_path is not None:
            try:
                save_identity_map(self._identity_state_path,
                                  self._host_identity_idx)
            except OSError as e:  # noqa: BLE001
                log.debug("could not persist identity map: %s", e)

    # ----- HTTP plumbing -----

    def _do_get(self, url: str, headers: Mapping[str, str] | None) -> CachedResponse:
        host = urlparse(url).netloc or url
        ident, idx = self._identity_for(host)
        session = self._session_for(host, idx)

        merged: dict[str, str] = ident.navigation_headers() if ident.user_agent else {}
        if headers:
            merged.update(headers)

        proxy = self.proxy_rotator.pick_for(host, idx)
        proxies = {"http": proxy.url, "https": proxy.url} if proxy else None
        r = session.get(
            url,
            headers=merged if merged else None,
            timeout=self.timeout_s,
            proxies=proxies,
        )
        return CachedResponse(
            text=r.text,
            content=r.content,
            status_code=r.status_code,
            headers=dict(r.headers),
            url=str(r.url),
            from_cache=False,
        )

    def _warm(self, url: str, headers: Mapping[str, str] | None) -> None:
        if not self.warm_session:
            return
        host = urlparse(url).netloc
        if not host or host in self._warmed_hosts:
            return
        home = homepage_url(url)
        try:
            self.rate_limiter.acquire(home)
            self._do_get(home, headers)
            self._warmed_hosts.add(host)
            log.debug("warmed session for %s", host)
        except Exception as e:  # noqa: BLE001
            log.debug("warmup failed for %s: %s", host, e)

    def get(self, url: str,
            headers: Mapping[str, str] | None = None,
            bypass_cache: bool = False) -> CachedResponse:
        """GET a URL with stealth, caching, rate limit, and retries."""
        if self.cache is not None and not bypass_cache:
            hit = self.cache.get("GET", url, headers)
            if hit is not None:
                log.debug("cache hit: %s (stored %s)", url, hit.stored_at_utc)
                return CachedResponse(
                    text=hit.body.decode("utf-8", errors="replace"),
                    content=hit.body,
                    status_code=hit.status_code,
                    headers=hit.headers,
                    url=hit.url,
                    from_cache=True,
                )
            if self.cache.is_replay:
                raise CassetteMiss(
                    f"no cassette entry for GET {url} (replay mode, no network)")

        self._warm(url, headers)
        host = urlparse(url).netloc or url

        def _attempt() -> CachedResponse:
            self.rate_limiter.acquire(url)
            return self._do_get(url, headers)

        def _retry_check(value_or_exc) -> bool:
            if isinstance(value_or_exc, Exception):
                name = type(value_or_exc).__name__.lower()
                return any(s in name for s in ("connection", "timeout", "transport"))
            if value_or_exc.status_code in RETRY_STATUSES:
                return True
            # A 200 with a challenge fingerprint is still a block: rotate
            # identity and retry, but only if we have another identity to try.
            verdict = classify_challenge(
                value_or_exc.status_code, value_or_exc.headers,
                value_or_exc.text or "")
            if verdict.blocked and verdict.kind != "ratelimit":
                log.warning("block detected on %s: %s/%s", url,
                            verdict.vendor, verdict.kind)
                if len(self.identity_pool) > 1:
                    self._rotate_identity(host)
                    return True
            return False

        resp = retry_with_backoff(
            _attempt,
            max_attempts=self.max_retries,
            is_retryable=_retry_check,
        )

        # Cache 2xx responses only when they look real (no block fingerprint).
        if (self.cache is not None
                and 200 <= resp.status_code < 300
                and not classify_challenge(
                    resp.status_code, resp.headers, resp.text or "").blocked):
            self.cache.put(
                "GET", url, headers,
                body=resp.content,
                status_code=resp.status_code,
                response_headers=resp.headers,
            )
        return resp

    def close(self) -> None:
        for s in self._sessions.values():
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
        self._sessions.clear()

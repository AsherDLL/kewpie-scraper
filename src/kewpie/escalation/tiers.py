"""The three ladder tiers: cheap HTTP, impersonation, headless browser.

Each implements the ``Fetcher`` protocol. None of them cache or consult the
learned policy - that is the ``EscalatingFetcher``'s job. They differ only in
how hard they work to look like a real browser.
"""
from __future__ import annotations

import logging
from time import perf_counter
from typing import Optional

from ..engine.client import StealthClient
from ..engine.identity import DEFAULT_POOL, Identity
from ..engine.proxies import ProxyConfig, ProxyRotator
from ..engine.rate_limit import PerHostRateLimiter
from ..models import FetchResult

log = logging.getLogger(__name__)

try:  # curl_cffi is a core dep; guard only to give a clean message.
    from curl_cffi import requests as cc_requests
except ImportError:  # pragma: no cover
    cc_requests = None  # type: ignore[assignment]

_DEFAULT_CONTACT_UA = "kewpie/0.1 (+https://github.com/AsherDLL/kewpie-crawler)"


class CheapHttpTier:
    """Plain HTTP with no browser impersonation. Fast; for well-behaved hosts.

    Uses curl_cffi's default TLS (not a browser fingerprint) plus a descriptive
    contact User-Agent. Good enough for RSS/JSON APIs and sites with no bot
    management; when it trips a fingerprint check, the ladder escalates.
    """
    name = "cheap"

    def __init__(self, rate_limit_per_second: float = 1.0,
                 user_agent: str = _DEFAULT_CONTACT_UA, timeout_s: float = 15.0):
        self._rate = PerHostRateLimiter(rate_limit_per_second)
        self._ua = user_agent
        self._timeout = timeout_s
        self._session = cc_requests.Session() if cc_requests else None

    def available(self) -> bool:
        return self._session is not None

    def fetch(self, url: str, *, headers: Optional[dict] = None,
              identity: Optional[Identity] = None,
              proxy: Optional[ProxyConfig] = None,
              wait_for: Optional[str] = None) -> FetchResult:
        self._rate.acquire(url)
        h = {"User-Agent": self._ua, "Accept": "*/*"}
        if headers:
            h.update(headers)
        proxies = {"http": proxy.url, "https": proxy.url} if proxy else None
        t0 = perf_counter()
        r = self._session.get(url, headers=h, timeout=self._timeout,
                              proxies=proxies)
        return FetchResult(
            url=url, final_url=str(r.url), status_code=r.status_code,
            text=r.text, content=r.content, headers=dict(r.headers),
            cookies=_safe_cookies(r), tier=self.name,
            elapsed_s=perf_counter() - t0,
        )


class ImpersonateTier:
    """Full curl_cffi browser impersonation via ``StealthClient``.

    Owns identity rotation, coherent headers, session warmup and per-host
    rate limiting. Caching is intentionally disabled here so the ladder owns a
    single cache/cassette across all tiers.
    """
    name = "impersonate"

    def __init__(self, rate_limit_per_second: float = 0.5,
                 identity_pool: tuple[Identity, ...] = DEFAULT_POOL,
                 proxy_rotator: Optional[ProxyRotator] = None,
                 warm_session: bool = True,
                 identity_state_path=None,
                 timeout_s: float = 30.0):
        self._client = StealthClient(
            rate_limit_per_second=rate_limit_per_second,
            cache_dir=None,  # ladder owns caching
            max_retries=3,
            proxy_rotator=proxy_rotator,
            default_timeout_s=timeout_s,
            warm_session=warm_session,
            identity_pool=identity_pool,
            identity_state_path=identity_state_path,
        )

    def available(self) -> bool:
        return True

    def fetch(self, url: str, *, headers: Optional[dict] = None,
              identity: Optional[Identity] = None,
              proxy: Optional[ProxyConfig] = None,
              wait_for: Optional[str] = None) -> FetchResult:
        t0 = perf_counter()
        r = self._client.get(url, headers=headers, bypass_cache=True)
        return FetchResult(
            url=url, final_url=r.url, status_code=r.status_code,
            text=r.text, content=r.content, headers=r.headers,
            cookies={}, tier=self.name, elapsed_s=perf_counter() - t0,
        )

    def close(self) -> None:
        self._client.close()


class BrowserTier:
    """Headless-browser rendering tier, backed by an optional backend.

    Available only when an extra (``kewpie[browser]``) is installed and the
    backend reports ready. When unavailable the ladder logs and stops below it.
    """
    name = "browser"

    def __init__(self, backend=None):
        self._backend = backend

    def available(self) -> bool:
        return self._backend is not None and self._backend.available()

    def fetch(self, url: str, *, headers: Optional[dict] = None,
              identity: Optional[Identity] = None,
              proxy: Optional[ProxyConfig] = None,
              wait_for: Optional[str] = None) -> FetchResult:
        if self._backend is None:
            raise RuntimeError("browser tier requested but no backend installed")
        return self._backend.fetch(url, headers=headers, identity=identity,
                                   proxy=proxy, wait_for=wait_for)


def _safe_cookies(response) -> dict:
    try:
        return {c.name: c.value for c in response.cookies.jar}  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        try:
            return dict(response.cookies)
        except Exception:  # noqa: BLE001
            return {}

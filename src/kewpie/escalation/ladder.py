"""EscalatingFetcher: the signal-driven escalation ladder.

Runs the cheapest viable tier first, classifies the response, and moves up a
tier only when a structured ``Verdict`` (or an empty-body heuristic) says the
current tier was blocked. Owns the single cache/cassette and the learned
per-host policy so tiers stay simple.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from ..challenge import classify_challenge
from ..engine.cache import DiskCache
from ..engine.client import CassetteMiss
from ..engine.identity import DEFAULT_POOL, pick_for_host
from ..engine.proxies import ProxyRotator
from ..models import FetchResult, Verdict
from .policy import PerHostPolicyStore
from .tiers import BrowserTier, CheapHttpTier, ImpersonateTier

log = logging.getLogger(__name__)

_TIER_INDEX = {"cheap": 0, "impersonate": 1, "browser": 2}
_EMPTY_BODY_THRESHOLD = 500


class EscalatingFetcher:
    def __init__(self,
                 cache_dir: Path | str | None = None,
                 cache_ttl_hours: float = 6.0,
                 cassette_mode: str = "off",
                 rate_limit_per_second: float = 0.5,
                 user_agent_contact: str | None = None,
                 max_tier: str = "browser",
                 identity_pool=DEFAULT_POOL,
                 proxy_rotator: Optional[ProxyRotator] = None,
                 state_dir: Path | str | None = None,
                 browser_backend="auto"):
        self.cache = (
            DiskCache(cache_dir, ttl_hours=cache_ttl_hours, mode=cassette_mode)
            if cache_dir else None
        )
        self.identity_pool = identity_pool
        self.proxy_rotator = proxy_rotator or ProxyRotator.from_env()
        state = Path(state_dir) if state_dir else None
        policy_path = (state / "policy.json") if state else None
        id_state = (state / "identities.json") if state else None
        self.policy = PerHostPolicyStore(policy_path, max_tier_index=2)

        cheap_ua = user_agent_contact
        self._tiers = [
            CheapHttpTier(rate_limit_per_second=max(rate_limit_per_second, 1.0),
                          user_agent=cheap_ua) if cheap_ua else
            CheapHttpTier(rate_limit_per_second=max(rate_limit_per_second, 1.0)),
            ImpersonateTier(rate_limit_per_second=rate_limit_per_second,
                            identity_pool=identity_pool,
                            proxy_rotator=self.proxy_rotator,
                            identity_state_path=id_state),
            BrowserTier(backend=_resolve_backend(browser_backend)),
        ]
        self.max_tier_index = min(_TIER_INDEX.get(max_tier, 2),
                                  len(self._tiers) - 1)

    # ----- public API -----

    def fetch(self, url: str, *, want_body: bool = True,
              max_tier: str | None = None,
              wait_for: str | None = None,
              headers: dict | None = None,
              bypass_cache: bool = False) -> FetchResult:
        host = urlparse(url).netloc or url
        cap = (min(_TIER_INDEX.get(max_tier, self.max_tier_index),
                   len(self._tiers) - 1)
               if max_tier else self.max_tier_index)

        if not bypass_cache:
            cached = self._cache_get(url)
            if cached is not None:
                return cached
            if self.cache is not None and self.cache.is_replay:
                raise CassetteMiss(f"no cassette entry for {url} (replay mode)")

        start = min(max(self.policy.start_tier(host), 0), cap)
        last: FetchResult | None = None
        last_exc: Exception | None = None

        for idx in range(start, cap + 1):
            tier = self._tiers[idx]
            if not tier.available():
                if tier.name == "browser":
                    log.info("browser tier unavailable for %s; "
                             "install 'kewpie[browser]' to enable it", host)
                continue
            identity = pick_for_host(host, self.identity_pool)
            proxy = self.proxy_rotator.pick_for(host, idx)
            try:
                result = tier.fetch(url, headers=headers, identity=identity,
                                    proxy=proxy, wait_for=wait_for)
            except Exception as e:  # noqa: BLE001
                last_exc = e
                log.warning("tier %s failed for %s: %s", tier.name, url, e)
                self.policy.record(host, idx, ok=False)
                continue

            verdict = classify_challenge(result.status_code, result.headers,
                                         result.text, result.cookies)
            result.verdict = verdict
            last = result

            if not self._should_escalate(verdict, result, want_body, idx, cap):
                self.policy.record(host, idx, ok=result.ok, vendor=verdict.vendor)
                if result.ok:
                    self._cache_put(url, result)
                return result
            self.policy.record(host, idx, ok=False, vendor=verdict.vendor)

        if last is not None:
            log.info("exhausted tiers for %s (verdict=%s/%s); returning best "
                     "effort - may need a dedicated solver", url,
                     last.verdict.vendor if last.verdict else None,
                     last.verdict.kind if last.verdict else None)
            return last
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"no ladder tier was available to fetch {url}")

    def close(self) -> None:
        for t in self._tiers:
            close = getattr(t, "close", None)
            if callable(close):
                close()

    # ----- internals -----

    def _should_escalate(self, verdict: Verdict, result: FetchResult,
                         want_body: bool, idx: int, cap: int) -> bool:
        if idx >= cap:
            return False
        if not any(self._tiers[j].available() for j in range(idx + 1, cap + 1)):
            return False
        if verdict.blocked and verdict.escalate:
            return True
        if (want_body and verdict.kind == "none"
                and self._looks_empty(result)):
            return True
        return False

    @staticmethod
    def _looks_empty(result: FetchResult) -> bool:
        if not (200 <= result.status_code < 300):
            return False
        ctype = str(result.headers.get("content-type")
                    or result.headers.get("Content-Type") or "")
        text = result.text or ""
        if "html" not in ctype.lower() and "<html" not in text[:200].lower():
            return False
        return len(text.strip()) < _EMPTY_BODY_THRESHOLD

    def _cache_get(self, url: str) -> FetchResult | None:
        if self.cache is None:
            return None
        hit = self.cache.get("GET", url)
        if hit is None:
            return None
        tier = hit.headers.get("x-kewpie-tier", "cache")
        return FetchResult(
            url=url, final_url=hit.url, status_code=hit.status_code,
            text=hit.body.decode("utf-8", errors="replace"), content=hit.body,
            headers=hit.headers, cookies={}, tier=tier,
            verdict=Verdict(), from_cache=True,
        )

    def _cache_put(self, url: str, result: FetchResult) -> None:
        if self.cache is None:
            return
        headers = dict(result.headers)
        headers["x-kewpie-tier"] = result.tier
        self.cache.put("GET", url, None, body=result.content,
                       status_code=result.status_code, response_headers=headers)


def _resolve_backend(browser_backend):
    if browser_backend is None:
        return None
    if browser_backend == "auto":
        from ..browser import load_default_browser_backend
        return load_default_browser_backend()
    return browser_backend

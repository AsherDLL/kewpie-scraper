"""robots.txt gate for the plain web-scraping mode.

Fetches and caches each host's robots.txt (via the cheap tier) and answers
allow/deny + crawl-delay using protego. RSS and official APIs are sanctioned
interfaces and do not go through this gate; plain web scraping does.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class RobotsGate:
    def __init__(self, fetcher, user_agent: str, enabled: bool = True):
        self._fetcher = fetcher
        self._ua = user_agent
        self._enabled = enabled
        self._cache: dict[str, object] = {}

    def _rules_for(self, url: str):
        p = urlparse(url)
        host = p.netloc
        if host in self._cache:
            return self._cache[host]
        robots_url = f"{p.scheme}://{host}/robots.txt"
        rules = None
        try:
            from protego import Protego
            res = self._fetcher.fetch(robots_url, want_body=True,
                                      max_tier="impersonate")
            text = res.text if res.ok else ""
            rules = Protego.parse(text or "")
        except Exception as e:  # noqa: BLE001
            log.debug("robots fetch/parse failed for %s: %s", host, e)
            rules = None  # fail open (allow) when robots is unreachable
        self._cache[host] = rules
        return rules

    def allowed(self, url: str) -> bool:
        if not self._enabled:
            return True
        rules = self._rules_for(url)
        if rules is None:
            return True
        try:
            return bool(rules.can_fetch(url, self._ua))
        except Exception:  # noqa: BLE001
            return True

    def crawl_delay(self, url: str) -> float | None:
        if not self._enabled:
            return None
        rules = self._rules_for(url)
        if rules is None:
            return None
        try:
            d = rules.crawl_delay(self._ua)
            return float(d) if d is not None else None
        except Exception:  # noqa: BLE001
            return None

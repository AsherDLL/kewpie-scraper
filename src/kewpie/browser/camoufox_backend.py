"""Camoufox headless-browser backend (optional extra: ``kewpie[camoufox]``).

Camoufox is a Firefox hard-fork that spoofs fingerprints at the C++ engine
level, so JS-side checks cannot see the automation. It exposes a Playwright
(sync) API. This is an alternative to the nodriver backend behind the same
``BrowserFetcher`` protocol; pick whichever a given target responds to.
"""
from __future__ import annotations

import logging
from time import perf_counter
from typing import Optional

from ..engine.identity import Identity
from ..engine.proxies import ProxyConfig
from ..models import FetchResult

log = logging.getLogger(__name__)


class CamoufoxFetcher:
    name = "camoufox"

    def __init__(self, headless: bool = True, settle_ms: int = 2500):
        self._headless = headless
        self._settle_ms = settle_ms
        self._cm = None
        self._browser = None

    def available(self) -> bool:
        try:
            import camoufox  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_browser(self, proxy: Optional[ProxyConfig]):
        if self._browser is not None:
            return
        from camoufox.sync_api import Camoufox
        kwargs: dict = {"headless": self._headless}
        if proxy is not None:
            kwargs["proxy"] = {"server": proxy.url}
        self._cm = Camoufox(**kwargs)
        self._browser = self._cm.__enter__()

    def fetch(self, url: str, *, headers: Optional[dict] = None,
              identity: Optional[Identity] = None,
              proxy: Optional[ProxyConfig] = None,
              wait_for: Optional[str] = None,
              timeout_s: float = 30.0) -> FetchResult:
        t0 = perf_counter()
        self._ensure_browser(proxy)
        page = self._browser.new_page()
        try:
            page.goto(url, timeout=int(timeout_s * 1000))
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=int(timeout_s * 1000))
                except Exception as e:  # noqa: BLE001
                    log.debug("wait_for %s timed out: %s", wait_for, e)
            else:
                page.wait_for_timeout(self._settle_ms)
            html = page.content()
            final_url = page.url
            cookies = {c["name"]: c.get("value", "")
                       for c in page.context.cookies()}
        finally:
            page.close()
        return FetchResult(
            url=url, final_url=final_url or url, status_code=200,
            text=html, content=html.encode("utf-8", errors="replace"),
            headers={"content-type": "text/html; charset=utf-8"},
            cookies=cookies, tier="browser", elapsed_s=perf_counter() - t0,
        )

    def close(self) -> None:
        if self._cm is not None:
            try:
                self._cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        self._cm = None
        self._browser = None

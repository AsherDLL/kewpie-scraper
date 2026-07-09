"""nodriver headless-browser backend (optional extra: ``kewpie[browser]``).

nodriver drives a system Chrome over plain CDP with no Selenium/Playwright in
the loop, which independent benchmarks show is the automation-protocol layer
that current Cloudflare gates key on. We render the page, optionally wait for a
selector or a short settle, then return the rendered HTML and cookies so the
challenge classifier can confirm the challenge cleared.

nodriver is async; we drive it from a private event loop so the public
``fetch`` stays synchronous like the other tiers. The browser is started lazily
and reused across fetches.
"""
from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Optional

from ..engine.identity import Identity
from ..engine.proxies import ProxyConfig
from ..models import FetchResult

log = logging.getLogger(__name__)


class NodriverFetcher:
    name = "nodriver"

    def __init__(self, headless: bool = True, settle_s: float = 2.5):
        self._headless = headless
        self._settle_s = settle_s
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._browser = None

    def available(self) -> bool:
        try:
            import nodriver  # noqa: F401
            return True
        except ImportError:
            return False

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def fetch(self, url: str, *, headers: Optional[dict] = None,
              identity: Optional[Identity] = None,
              proxy: Optional[ProxyConfig] = None,
              wait_for: Optional[str] = None,
              timeout_s: float = 30.0) -> FetchResult:
        t0 = perf_counter()
        loop = self._get_loop()
        html, cookies, final_url = loop.run_until_complete(
            self._render(url, identity, proxy, wait_for, timeout_s))
        return FetchResult(
            url=url, final_url=final_url or url, status_code=200,
            text=html, content=html.encode("utf-8", errors="replace"),
            headers={"content-type": "text/html; charset=utf-8"},
            cookies=cookies, tier="browser", elapsed_s=perf_counter() - t0,
        )

    async def _render(self, url, identity, proxy, wait_for, timeout_s):
        import nodriver

        if self._browser is None:
            args = []
            if identity is not None and identity.user_agent:
                args.append(f"--user-agent={identity.user_agent}")
                if identity.accept_language:
                    args.append("--accept-lang="
                                f"{identity.accept_language.split(',')[0]}")
            if proxy is not None:
                args.append(f"--proxy-server={proxy.url}")
            self._browser = await nodriver.start(
                headless=self._headless, browser_args=args or None)

        tab = await self._browser.get(url)
        if wait_for:
            try:
                await tab.wait_for(wait_for, timeout=timeout_s)
            except Exception as e:  # noqa: BLE001
                log.debug("wait_for %s timed out: %s", wait_for, e)
        else:
            await tab.sleep(self._settle_s)

        html = await tab.get_content()
        cookies: dict = {}
        try:
            for c in await self._browser.cookies.get_all():
                name = getattr(c, "name", None)
                if name:
                    cookies[name] = getattr(c, "value", "")
        except Exception:  # noqa: BLE001
            pass
        final_url = url
        try:
            final_url = await tab.evaluate("window.location.href") or url
        except Exception:  # noqa: BLE001
            pass
        return html, cookies, final_url

    def close(self) -> None:
        if self._browser is not None and self._loop is not None:
            try:
                self._loop.run_until_complete(self._browser.stop())
            except Exception:  # noqa: BLE001
                pass
        if self._loop is not None:
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001
                pass
        self._browser = None
        self._loop = None

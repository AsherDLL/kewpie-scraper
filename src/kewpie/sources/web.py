"""Plain web-scraping source adapter (list page -> article detail pages).

Fetches one or more index pages, extracts article links by CSS selector and/or
URL pattern, then fetches and extracts each article through the escalation
ladder. Honors robots.txt by default.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..extraction.html import extract
from ..models import RawDocument
from .base import (
    CollectContext, make_raw_document, passes_prefilter, resolve_prefilter,
)
from .robots import RobotsGate

log = logging.getLogger(__name__)


class WebSource:
    source_type = "web"

    def __init__(self, cfg: dict, ctx: CollectContext):
        self.cfg = cfg
        self.ctx = ctx
        self.source_id = cfg.get("id") or cfg.get("source_id") or cfg.get("name")
        self.source_name = cfg.get("name", self.source_id)
        self.start_urls = cfg.get("start_urls") or ([cfg["url"]] if cfg.get("url") else [])
        self.link_selector = cfg.get("link_selector", "a")
        self.url_pattern = re.compile(cfg["url_pattern"]) if cfg.get("url_pattern") else None
        self.max_links = int(cfg.get("max_links", ctx.max_items))
        self.max_tier = cfg.get("max_tier", "browser")
        self.base_confidence = float(cfg.get("base_confidence", 0.5))
        respect = cfg.get("respect_robots", ctx.defaults.get("respect_robots", True))
        ua = ctx.defaults.get("user_agent_contact", "kewpie")
        self.robots = RobotsGate(ctx.fetcher, ua, enabled=bool(respect))

    def _discover_links(self) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for start in self.start_urls:
            if not self.robots.allowed(start):
                log.info("robots.txt disallows index %s; skipping", start)
                continue
            try:
                res = self.ctx.fetcher.fetch(start, want_body=True,
                                             max_tier=self.max_tier)
            except Exception as e:  # noqa: BLE001
                log.warning("index fetch failed %s: %s", start, e)
                continue
            soup = BeautifulSoup(res.text or "", "lxml")
            for a in soup.select(self.link_selector):
                href = a.get("href")
                if not href:
                    continue
                url = urljoin(res.final_url or start, href)
                if self.url_pattern and not self.url_pattern.search(url):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                found.append(url)
                if len(found) >= self.max_links:
                    return found
        return found

    def collect(self) -> Iterable[RawDocument]:
        prefilter = resolve_prefilter(self.cfg, self.ctx)
        docs = []
        for url in self._discover_links():
            if not self.robots.allowed(url):
                log.info("robots.txt disallows %s; skipping", url)
                continue
            try:
                res = self.ctx.fetcher.fetch(url, want_body=True,
                                             max_tier=self.max_tier)
            except Exception as e:  # noqa: BLE001
                log.debug("article fetch failed %s: %s", url, e)
                continue
            if not res.ok or not res.text:
                continue
            doc = extract(res.text)
            fields = {"title": doc.title, "summary": doc.snippet,
                      "body": doc.body_text}
            if not passes_prefilter(fields, prefilter):
                continue
            docs.append(make_raw_document(
                url=url, final_url=res.final_url, source_id=self.source_id,
                source_name=self.source_name, source_type="web",
                title=doc.title, summary=doc.snippet, body_text=doc.body_text,
                author=doc.author, published_at_utc=doc.published_at_utc,
                fetch_tier=res.tier, lang=doc.lang,
                source_confidence=self.base_confidence,
            ))
        return docs

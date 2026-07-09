"""RSS / Atom source adapter.

RSS is a subscribe/consume operation, not scraping: we fetch the feed through
the engine (so we control TLS, UA, retries) and hand the bytes to feedparser,
which liberally parses malformed feeds and normalizes RSS/Atom into one model.
Conditional GET (ETag / Last-Modified) lets the server answer 304 when nothing
changed. Optionally, each entry's full article is fetched and extracted.
"""
from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

import feedparser

from ..extraction.html import extract
from ..models import RawDocument
from .base import (
    CollectContext, make_raw_document, passes_prefilter, resolve_prefilter,
)

log = logging.getLogger(__name__)


def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
    return None


class RssSource:
    source_type = "rss"

    def __init__(self, cfg: dict, ctx: CollectContext):
        self.cfg = cfg
        self.ctx = ctx
        self.url = cfg["url"]
        self.source_id = cfg.get("id") or cfg.get("source_id") or self.url
        self.source_name = cfg.get("name", self.source_id)
        self.base_confidence = float(cfg.get("base_confidence", 0.6))
        self.fetch_full_article = bool(cfg.get("fetch_full_article", True))

    def collect(self) -> Iterable[RawDocument]:
        cond = self.ctx.conditional.headers_for(self.url)
        result = self.ctx.fetcher.fetch(
            self.url, want_body=True, max_tier="impersonate", headers=cond or None)
        if result.status_code == 304:
            log.info("feed %s unchanged (304)", self.source_id)
            return []
        self.ctx.conditional.update(self.url, result.headers)

        parsed = feedparser.parse(result.content or result.text.encode("utf-8"))
        if parsed.bozo:
            log.debug("feed %s not well-formed: %s",
                      self.source_id, parsed.get("bozo_exception"))
        prefilter = resolve_prefilter(self.cfg, self.ctx)
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=self.ctx.since_hours)
                  if self.ctx.since_hours else None)

        docs = []
        for entry in parsed.entries[: self.ctx.max_items]:
            link = entry.get("link")
            if not link:
                continue
            published = _entry_datetime(entry)
            if cutoff and published and published < cutoff:
                continue
            title = entry.get("title", "")
            summary = entry.get("summary") or entry.get("description")
            if not passes_prefilter({"title": title, "summary": summary}, prefilter):
                continue

            body_text = summary
            fetch_tier = "rss"
            author = entry.get("author")
            if self.fetch_full_article:
                try:
                    art = self.ctx.fetcher.fetch(link, want_body=True)
                    if art.ok and art.text:
                        doc = extract(art.text, fallback_title=title)
                        if doc.body_text:
                            body_text = doc.body_text
                        author = author or doc.author
                        published = published or doc.published_at_utc
                        fetch_tier = art.tier
                except Exception as e:  # noqa: BLE001
                    log.debug("article fetch failed for %s: %s", link, e)

            docs.append(make_raw_document(
                url=link, source_id=self.source_id,
                source_name=self.source_name, source_type="rss",
                title=title, summary=summary, body_text=body_text,
                author=author, published_at_utc=published, fetch_tier=fetch_tier,
                lang=parsed.feed.get("language"),
                source_confidence=self.base_confidence,
            ))
        return docs

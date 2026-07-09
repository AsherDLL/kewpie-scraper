"""X / Twitter source adapter - best-effort by design.

The free X ecosystem is broken post-2023: snscrape is dead, Nitter is
intermittent, and timeline enumeration is impossible without the paid API. So:

- ``official``: the paid API v2 when a bearer token is configured.
- ``syndication``: hydrate specific tweet IDs via the public
  ``cdn.syndication.twimg.com`` endpoint (single tweets only; cannot list a
  timeline).
- ``auto``: official if a token is set, else syndication if tweet IDs are
  given, else a logged skip.
- ``off``: disabled.

Do not build core functionality on this source; treat it as a bonus.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Iterable

from ..models import RawDocument
from .base import CollectContext, make_raw_document
from .errors import AuthError

log = logging.getLogger(__name__)

_SYNDICATION = "https://cdn.syndication.twimg.com/tweet-result?id={id}&token=0"


class XSource:
    source_type = "x"

    def __init__(self, cfg: dict, ctx: CollectContext):
        self.cfg = cfg
        self.ctx = ctx
        self.mode = cfg.get("mode", "auto")
        self.query = cfg.get("query")
        self.tweet_ids = cfg.get("tweet_ids", [])
        self.source_id = cfg.get("id", "x")
        self.source_name = cfg.get("name", "x")
        self.base_confidence = float(cfg.get("base_confidence", 0.4))
        self.official = cfg.get("official", {})

    def collect(self) -> Iterable[RawDocument]:
        if self.mode == "off":
            return []
        token = os.environ.get(self.official.get("bearer_token_env", "X_BEARER_TOKEN"))
        if self.mode == "official" or (self.mode == "auto" and token):
            if not token:
                raise AuthError("x official mode: bearer token env var unset")
            return self._collect_official(token)
        if self.tweet_ids:
            return self._collect_syndication()
        log.warning("x source %s: no bearer token and no tweet_ids; free "
                    "timeline reading is unreliable in 2026 - skipping",
                    self.source_id)
        return []

    def _collect_official(self, token: str) -> Iterable[RawDocument]:
        from urllib.parse import urlencode
        endpoint = self.official.get(
            "endpoint", "https://api.twitter.com/2/tweets/search/recent")
        params = {"query": self.query or "",
                  "tweet.fields": "created_at,author_id,lang",
                  "max_results": min(int(self.cfg.get("limit", 25)), 100)}
        url = f"{endpoint}?{urlencode(params)}"
        res = self.ctx.fetcher.fetch(
            url, headers={"Authorization": f"Bearer {token}"},
            want_body=True, max_tier="impersonate")
        if res.status_code in (401, 403):
            raise AuthError(f"x official API auth failed ({res.status_code})")
        if not res.ok:
            log.warning("x official API %s -> %s", self.source_id, res.status_code)
            return []
        data = res.json().get("data", [])
        docs = []
        for t in data:
            tid = t.get("id", "")
            docs.append(self._doc(
                url=f"https://x.com/i/status/{tid}",
                title=(t.get("text", "")[:120]), body=t.get("text", ""),
                created=t.get("created_at"), author=t.get("author_id", ""),
                lang=t.get("lang")))
        return docs

    def _collect_syndication(self) -> Iterable[RawDocument]:
        docs = []
        for tid in self.tweet_ids:
            try:
                res = self.ctx.fetcher.fetch(
                    _SYNDICATION.format(id=tid), want_body=True,
                    max_tier="impersonate")
                if not res.ok:
                    continue
                data = res.json()
            except Exception as e:  # noqa: BLE001
                log.debug("syndication fetch failed for %s: %s", tid, e)
                continue
            user = data.get("user", {}) or {}
            docs.append(self._doc(
                url=f"https://x.com/i/status/{tid}",
                title=(data.get("text", "")[:120]), body=data.get("text", ""),
                created=data.get("created_at"),
                author=user.get("screen_name", ""), lang=data.get("lang")))
        return docs

    def _doc(self, url, title, body, created, author, lang=None) -> RawDocument:
        published = None
        if created:
            try:
                published = datetime.fromisoformat(
                    str(created).replace("Z", "+00:00"))
            except ValueError:
                published = None
        return make_raw_document(
            url=url, source_id=self.source_id, source_name=self.source_name,
            source_type="x", title=title, summary=body[:280], body_text=body,
            author=author or None, published_at_utc=published,
            fetch_tier=self.mode, lang=lang, source_confidence=self.base_confidence)

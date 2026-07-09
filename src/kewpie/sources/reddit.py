"""Reddit source adapter with three modes.

- ``rss`` (default): the public, no-auth ``/r/<sub>/<listing>/.rss`` feed,
  routed through the RSS adapter. ToS-friendly and needs no credentials.
- ``api``: the official Data API via PRAW, using the caller's own OAuth
  credentials (from env). For depth/search/higher volume.
- ``arctic_shift``: the community Arctic Shift archive for historical backfill
  (third-party, no SLA).

We never default to ``.json``/HTML scraping. A descriptive User-Agent is
required and datacenter IPs are throttled by Reddit; that is expected.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlencode

from ..models import RawDocument
from .base import CollectContext, make_raw_document, passes_prefilter, resolve_prefilter
from .errors import AuthError, ConfigError
from .rss import RssSource

log = logging.getLogger(__name__)


class RedditSource:
    source_type = "reddit"

    def __init__(self, cfg: dict, ctx: CollectContext):
        self.cfg = cfg
        self.ctx = ctx
        self.subreddit = cfg.get("subreddit")
        if not self.subreddit:
            raise ConfigError("reddit source requires 'subreddit'")
        self.listing = cfg.get("listing", "new")
        self.limit = int(cfg.get("limit", ctx.max_items))
        self.mode = cfg.get("mode", "rss")
        self.source_id = cfg.get("id") or f"reddit_{self.subreddit}"
        self.source_name = cfg.get("name", f"r/{self.subreddit}")
        self.base_confidence = float(cfg.get("base_confidence", 0.4))

    def collect(self) -> Iterable[RawDocument]:
        if self.mode == "rss":
            return self._collect_rss()
        if self.mode == "api":
            return self._collect_api()
        if self.mode == "arctic_shift":
            return self._collect_arctic_shift()
        raise ConfigError(f"unknown reddit mode: {self.mode}")

    def _collect_rss(self) -> Iterable[RawDocument]:
        url = f"https://www.reddit.com/r/{self.subreddit}/{self.listing}/.rss"
        inner = RssSource({
            "url": url, "id": self.source_id, "name": self.source_name,
            "base_confidence": self.base_confidence, "fetch_full_article": False,
            "prefilter": self.cfg.get("prefilter"),
        }, self.ctx)
        for doc in inner.collect() or []:
            doc.source_type = "reddit"
            yield doc

    def _collect_api(self) -> Iterable[RawDocument]:
        try:
            import praw
        except ImportError as e:
            raise AuthError("reddit api mode needs the 'reddit' extra "
                            "(pip install kewpie-crawler[reddit])") from e
        api = self.cfg.get("api", {})
        cid = os.environ.get(api.get("client_id_env", "REDDIT_CLIENT_ID"))
        secret = os.environ.get(api.get("client_secret_env", "REDDIT_CLIENT_SECRET"))
        ua = api.get("user_agent")
        if not cid or not secret:
            raise AuthError("reddit api mode: client id/secret env vars unset")
        if not ua:
            raise ConfigError("reddit api mode requires api.user_agent")
        reddit = praw.Reddit(client_id=cid, client_secret=secret, user_agent=ua)
        sub = reddit.subreddit(self.subreddit)
        listing_fn = getattr(sub, self.listing, None)
        if listing_fn is None:
            raise ConfigError(f"unknown reddit listing: {self.listing}")
        prefilter = resolve_prefilter(self.cfg, self.ctx)
        docs = []
        for s in listing_fn(limit=self.limit):
            title = getattr(s, "title", "")
            body = getattr(s, "selftext", "") or ""
            if not passes_prefilter({"title": title, "summary": body}, prefilter):
                continue
            docs.append(self._doc(
                url="https://www.reddit.com" + getattr(s, "permalink", ""),
                title=title, body=body,
                created=getattr(s, "created_utc", None),
                author=str(getattr(s, "author", "") or "")))
        return docs

    def _collect_arctic_shift(self) -> Iterable[RawDocument]:
        arctic = self.cfg.get("arctic_shift", {})
        endpoint = arctic.get("endpoint")
        if not endpoint:
            raise ConfigError("arctic_shift mode requires arctic_shift.endpoint")
        params = dict(arctic.get("params", {}))
        params.setdefault("subreddit", self.subreddit)
        params.setdefault("limit", self.limit)
        url = f"{endpoint}?{urlencode(params)}"
        res = self.ctx.fetcher.fetch(url, want_body=True, max_tier="impersonate")
        if not res.ok:
            log.warning("arctic_shift %s -> %s", self.source_id, res.status_code)
            return []
        try:
            payload = res.json()
        except Exception as e:  # noqa: BLE001
            log.warning("arctic_shift %s bad JSON: %s", self.source_id, e)
            return []
        items = payload.get("data", payload if isinstance(payload, list) else [])
        prefilter = resolve_prefilter(self.cfg, self.ctx)
        docs = []
        for post in items[: self.limit]:
            title = post.get("title", "")
            body = post.get("selftext", "") or ""
            if not passes_prefilter({"title": title, "summary": body}, prefilter):
                continue
            permalink = post.get("permalink", "")
            url = post.get("url") or ("https://www.reddit.com" + permalink)
            docs.append(self._doc(url=url, title=title, body=body,
                                  created=post.get("created_utc"),
                                  author=post.get("author", "")))
        return docs

    def _doc(self, url: str, title: str, body: str,
             created, author: str) -> RawDocument:
        published = None
        if created:
            try:
                published = datetime.fromtimestamp(float(created), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                published = None
        return make_raw_document(
            url=url, source_id=self.source_id, source_name=self.source_name,
            source_type="reddit", title=title, summary=body[:280],
            body_text=body, author=author or None, published_at_utc=published,
            fetch_tier=self.mode, source_confidence=self.base_confidence)

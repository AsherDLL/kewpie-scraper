"""Generic news-API source adapter.

Most providers (NewsAPI.org, GNews, NewsData.io, Mediastack, ...) differ only
in auth placement, the JSON path to the article array, and field names. This
adapter fits them all via config: ``auth`` (query vs header), ``items_path``,
``field_map``, and an ``ok_predicate`` because several providers return HTTP
200 with an error body. The API key is validated before the request; a missing
key is a clean skip, not a crash.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlencode

from ..models import RawDocument
from .base import CollectContext, make_raw_document, passes_prefilter, resolve_prefilter
from .errors import (
    AuthError, ConfigError, NotFoundError, QuotaError, RateLimitError,
    TransientError,
)

log = logging.getLogger(__name__)


def _dig(obj: Any, path: str) -> Any:
    """Follow a dotted path (e.g. 'source.name') through nested dicts."""
    cur = obj
    for key in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


class NewsApiSource:
    source_type = "newsapi"

    def __init__(self, cfg: dict, ctx: CollectContext):
        self.cfg = cfg
        self.ctx = ctx
        self.endpoint = cfg.get("endpoint")
        if not self.endpoint:
            raise ConfigError("newsapi source requires 'endpoint'")
        self.auth = cfg.get("auth", {})
        self.query_params = dict(cfg.get("query_params", {}))
        self.items_path = cfg.get("items_path", "articles")
        self.ok_predicate = cfg.get("ok_predicate")
        self.field_map = cfg.get("field_map", {})
        self.source_id = cfg.get("id") or cfg.get("name") or self.endpoint
        self.source_name = cfg.get("name", self.source_id)
        self.base_confidence = float(cfg.get("base_confidence", 0.6))

    def collect(self) -> Iterable[RawDocument]:
        # Validate credentials BEFORE any request.
        key_env = self.auth.get("key_env")
        key = os.environ.get(key_env) if key_env else None
        mode = self.auth.get("mode", "query")
        param = self.auth.get("param", "apiKey")
        if key_env and not key:
            raise AuthError(f"newsapi source {self.source_id} skipped: "
                            f"{key_env} not set")

        params = dict(self.query_params)
        headers: dict[str, str] = {}
        if key:
            if mode == "header":
                headers[param] = key
            else:
                params[param] = key
        url = f"{self.endpoint}?{urlencode(params)}"

        res = self.ctx.fetcher.fetch(url, headers=headers or None,
                                     want_body=True, max_tier="impersonate")
        self._raise_for_status(res.status_code, res.headers)

        try:
            payload = res.json()
        except Exception as e:  # noqa: BLE001
            raise TransientError(f"newsapi {self.source_id}: invalid JSON: {e}")
        self._check_ok_predicate(payload)

        items = _dig(payload, self.items_path) or []
        if not isinstance(items, list):
            raise TransientError(
                f"newsapi {self.source_id}: items_path did not yield a list")

        prefilter = resolve_prefilter(self.cfg, self.ctx)
        docs = []
        for item in items[: self.ctx.max_items]:
            mapped = {canon: _dig(item, path)
                      for canon, path in self.field_map.items()}
            title = mapped.get("title") or ""
            summary = mapped.get("summary")
            if not passes_prefilter({"title": title, "summary": summary}, prefilter):
                continue
            docs.append(make_raw_document(
                url=mapped.get("url") or "",
                source_id=self.source_id, source_name=self.source_name,
                source_type="newsapi", title=title, summary=summary,
                body_text=mapped.get("body") or summary,
                author=mapped.get("author"),
                published_at_utc=_parse_dt(mapped.get("published")),
                lang=mapped.get("language"),
                source_confidence=self.base_confidence))
        return docs

    def _raise_for_status(self, status: int, headers: dict) -> None:
        if status in (401, 403):
            raise AuthError(f"newsapi {self.source_id}: auth failed ({status})")
        if status == 404:
            raise NotFoundError(f"newsapi {self.source_id}: endpoint not found")
        if status == 429:
            lower = {k.lower(): v for k, v in (headers or {}).items()}
            retry_after = lower.get("retry-after")
            raise RateLimitError(
                f"newsapi {self.source_id}: rate limited",
                retry_after=float(retry_after) if retry_after else None)
        if status >= 500:
            raise TransientError(f"newsapi {self.source_id}: server error {status}")

    def _check_ok_predicate(self, payload: Any) -> None:
        if not self.ok_predicate:
            return
        field = self.ok_predicate.get("field")
        val = _dig(payload, field) if field else None
        if "not_equals" in self.ok_predicate:
            if val == self.ok_predicate["not_equals"]:
                self._raise_body_error(payload)
        elif "equals" in self.ok_predicate:
            if val != self.ok_predicate["equals"]:
                self._raise_body_error(payload)

    def _raise_body_error(self, payload: Any) -> None:
        code = str(_dig(payload, "code") or "").lower()
        message = _dig(payload, "message") or "provider returned an error body"
        if "rate" in code or "limit" in code or "maximum" in code:
            raise QuotaError(f"newsapi {self.source_id}: {message}")
        if "key" in code or "auth" in code:
            raise AuthError(f"newsapi {self.source_id}: {message}")
        raise TransientError(f"newsapi {self.source_id}: {message}")


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

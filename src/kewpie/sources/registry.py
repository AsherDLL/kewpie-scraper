"""Static source-type -> adapter dispatch (no plugin discovery)."""
from __future__ import annotations

from .base import CollectContext
from .errors import ConfigError
from .newsapi import NewsApiSource
from .reddit import RedditSource
from .rss import RssSource
from .web import WebSource
from .x import XSource

ADAPTERS = {
    "rss": RssSource,
    "web": WebSource,
    "reddit": RedditSource,
    "x": XSource,
    "newsapi": NewsApiSource,
}


def build_adapter(cfg: dict, ctx: CollectContext):
    source_type = cfg.get("type")
    cls = ADAPTERS.get(source_type)
    if cls is None:
        raise ConfigError(
            f"unknown source type {source_type!r}; "
            f"known types: {', '.join(sorted(ADAPTERS))}")
    return cls(cfg, ctx)

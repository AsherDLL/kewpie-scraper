"""Config-driven ingestion adapters: rss, web, reddit, x, newsapi."""
from __future__ import annotations

from .base import CollectContext, SourceAdapter
from .errors import (
    AuthError, ConfigError, NotFoundError, QuotaError, RateLimitError,
    SourceError, TransientError,
)
from .registry import ADAPTERS, build_adapter

__all__ = [
    "CollectContext", "SourceAdapter", "build_adapter", "ADAPTERS",
    "SourceError", "ConfigError", "AuthError", "RateLimitError",
    "QuotaError", "NotFoundError", "TransientError",
]

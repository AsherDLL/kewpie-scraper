"""Kewpie Crawler: a reusable, anti-bot-resistant, config-driven collector.

Public API is assembled here. Submodules that pull optional dependencies
(browser backends, PRAW) are import-guarded and not imported at package load.
"""
from __future__ import annotations

from .challenge import Verdict, classify_challenge, detect_block
from .engine import CachedResponse, DEFAULT_POOL, Identity, StealthClient
from .models import (
    ExtractedDocument, ExtractedSignal, FetchResult, RawDocument,
)

__version__ = "0.1.0"

__all__ = [
    "StealthClient", "CachedResponse", "Identity", "DEFAULT_POOL",
    "classify_challenge", "detect_block", "Verdict",
    "FetchResult", "RawDocument", "ExtractedDocument", "ExtractedSignal",
    "__version__",
]


def __getattr__(name: str):
    # Lazily expose the escalation/pipeline API so importing the base package
    # stays cheap and does not require optional extras.
    if name in ("EscalatingFetcher", "Fetcher"):
        from .escalation import EscalatingFetcher, Fetcher
        return {"EscalatingFetcher": EscalatingFetcher, "Fetcher": Fetcher}[name]
    if name in ("collect", "extract"):
        from . import pipeline
        return getattr(pipeline, name)
    raise AttributeError(f"module 'kewpie' has no attribute {name!r}")

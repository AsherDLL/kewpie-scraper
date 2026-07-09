"""Boundary data models shared across Kewpie.

Two flavours on purpose:

- ``Verdict``, ``RawDocument``, ``ExtractedDocument`` and ``ExtractedSignal``
  are Pydantic models: they cross serialization boundaries (parquet, JSON,
  config) and benefit from validation.
- ``FetchResult`` is a plain dataclass: it is created on every HTTP response
  and carries raw bytes + full text, so we skip per-response validation.
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ChallengeKind = Literal[
    "none", "interstitial", "captcha", "turnstile",
    "ratelimit", "js_challenge", "empty",
]
SourceType = Literal["rss", "web", "reddit", "x", "newsapi"]


class Verdict(BaseModel):
    """Structured result of the WAF / challenge classifier."""
    blocked: bool = False
    vendor: Optional[str] = None
    kind: ChallengeKind = "none"
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    escalate: bool = False


@dataclass
class FetchResult:
    """A fetched response plus the tier and challenge verdict that produced it."""
    url: str
    final_url: str
    status_code: int
    text: str
    content: bytes
    headers: dict
    cookies: dict = field(default_factory=dict)
    tier: str = "impersonate"
    verdict: Optional[Verdict] = None
    from_cache: bool = False
    elapsed_s: float = 0.0

    def json(self) -> Any:
        return _json.loads(self.text)

    @property
    def ok(self) -> bool:
        if self.verdict is not None and self.verdict.blocked:
            return False
        # 304 Not Modified is a valid, successful conditional-GET response.
        return (200 <= self.status_code < 300) or self.status_code == 304


class RawDocument(BaseModel):
    """One collected document, before vocabulary extraction."""
    url: str
    final_url: Optional[str] = None
    source_id: str
    source_name: str
    source_type: SourceType
    title: str = ""
    summary: Optional[str] = None
    body_text: Optional[str] = None
    raw_html: Optional[str] = None
    content_hash: str = ""
    author: Optional[str] = None
    published_at_utc: Optional[datetime] = None
    collected_at_utc: Optional[datetime] = None
    fetch_tier: Optional[str] = None
    lang: Optional[str] = None
    source_confidence: float = 0.5
    byte_size: int = 0


class ExtractedDocument(BaseModel):
    """Article body + metadata parsed from an HTML page."""
    title: str
    body_text: str
    snippet: str
    published_at_utc: Optional[datetime] = None
    author: Optional[str] = None
    canonical_url: Optional[str] = None
    lang: Optional[str] = None


class ExtractedSignal(BaseModel):
    """One (entity, document, signal) proximity hit from the extract stage."""
    entity_id: int | str
    entity_name: str
    signal: str
    signal_class: str
    proximity_chars: int
    evidence: str
    url: Optional[str] = None
    source_id: Optional[str] = None
    source_confidence: Optional[float] = None
    published_at_utc: Optional[datetime] = None
    collected_at_utc: Optional[datetime] = None
    extra: dict[str, Any] = Field(default_factory=dict)

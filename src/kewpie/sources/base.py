"""Shared context, protocol, and helpers for source adapters."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional, Protocol

from ..escalation.ladder import EscalatingFetcher
from ..models import RawDocument
from .conditional import ConditionalStore


@dataclass
class CollectContext:
    """Everything an adapter needs, wired once by the pipeline."""
    fetcher: EscalatingFetcher
    conditional: ConditionalStore
    defaults: dict = field(default_factory=dict)
    prefilter_default: Optional[dict] = None
    max_items: int = 25
    since_hours: Optional[float] = None
    force_prefilter: bool = False


class SourceAdapter(Protocol):
    source_type: str

    def collect(self) -> Iterable[RawDocument]:
        ...


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="replace"))
        h.update(b"\n")
    return h.hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def resolve_prefilter(source_cfg: dict, ctx: CollectContext) -> Optional[dict]:
    """The effective prefilter for a source.

    Per-source ``prefilter`` wins; otherwise the global default applies only
    when the caller forced it (``kewpie collect --prefilter``). Collect-raw is
    the default, so an unforced default prefilter stays off.
    """
    pf = source_cfg.get("prefilter")
    if pf is not None:
        return pf
    if ctx.force_prefilter and ctx.prefilter_default:
        return ctx.prefilter_default
    return None


def passes_prefilter(fields: dict, prefilter: Optional[dict]) -> bool:
    """True if the item should be kept. No prefilter or disabled -> keep."""
    if not prefilter or not prefilter.get("enabled", False):
        return True
    keywords = [k for k in prefilter.get("keywords", []) if k]
    if not keywords:
        return True
    case_sensitive = bool(prefilter.get("case_sensitive", False))
    look_fields = prefilter.get("fields", ["title", "summary"])
    text = " ".join(str(fields.get(f) or "") for f in look_fields)
    if not case_sensitive:
        text = text.lower()
        keywords = [k.lower() for k in keywords]
    hits = [k in text for k in keywords]
    return all(hits) if prefilter.get("match", "any") == "all" else any(hits)


def make_raw_document(*, url: str, source_id: str, source_name: str,
                      source_type: str, title: str = "",
                      summary: Optional[str] = None,
                      body_text: Optional[str] = None,
                      raw_html: Optional[str] = None,
                      author: Optional[str] = None,
                      published_at_utc: Optional[datetime] = None,
                      final_url: Optional[str] = None,
                      fetch_tier: Optional[str] = None,
                      lang: Optional[str] = None,
                      source_confidence: float = 0.5) -> RawDocument:
    body_for_size = body_text or summary or title or ""
    return RawDocument(
        url=url, final_url=final_url, source_id=source_id,
        source_name=source_name, source_type=source_type, title=title or "",
        summary=summary, body_text=body_text, raw_html=raw_html, author=author,
        published_at_utc=published_at_utc, collected_at_utc=now_utc(),
        fetch_tier=fetch_tier, lang=lang, source_confidence=source_confidence,
        content_hash=content_hash(url, title or "", body_for_size),
        byte_size=len(body_for_size.encode("utf-8", errors="replace")),
    )

"""Extract article body text + metadata from HTML.

Heuristic-based; works adequately on most modern article pages. We prefer the
<article>, <main>, or first <div role="main"> as the body root, then collect
all <p> text, falling back to all <p> on the page. No JS engine: pages that
hydrate their body client-side extract empty here and the ladder's browser tier
is the escalation path for those.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..models import ExtractedDocument

_BODY_SELECTORS = (
    "article",
    "main",
    'div[role="main"]',
    "div.article-body",
    "div.story-body",
    "div.entry-content",
)


def _select_body(soup: BeautifulSoup):
    for sel in _BODY_SELECTORS:
        el = soup.select_one(sel)
        if el is not None:
            return el
    return soup  # whole page fallback


def _collect_paragraphs(root) -> list[str]:
    out = []
    for p in root.find_all("p"):
        text = p.get_text(" ", strip=True)
        if text and len(text) > 20:  # drop nav/footer junk
            out.append(text)
    return out


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def extract(html: str, fallback_title: str = "") -> ExtractedDocument:
    """Return an ExtractedDocument from an HTML page.

    Always returns an object (never None); empty body_text means the extractor
    could not find content. The caller decides whether to store or escalate.
    """
    soup = BeautifulSoup(html, "lxml")

    title = fallback_title
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og_title = soup.select_one('meta[property="og:title"]')
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()

    body_root = _select_body(soup)
    paragraphs = _collect_paragraphs(body_root)
    body_text = _normalize_whitespace("\n\n".join(paragraphs))

    snippet = body_text[:280] + ("..." if len(body_text) > 280 else "")

    published_at = None
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        try:
            published_at = datetime.fromisoformat(
                time_tag["datetime"].replace("Z", "+00:00"))
        except ValueError:
            pass

    author = None
    author_meta = soup.select_one('meta[name="author"]')
    if author_meta and author_meta.get("content"):
        author = author_meta["content"].strip()

    canonical = soup.select_one('link[rel="canonical"]')
    canonical_url = (canonical["href"]
                     if canonical and canonical.get("href") else None)

    lang = None
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        lang = str(html_tag["lang"]).split("-")[0] or None

    return ExtractedDocument(
        title=_normalize_whitespace(title),
        body_text=body_text,
        snippet=snippet,
        published_at_utc=published_at,
        author=author,
        canonical_url=canonical_url,
        lang=lang,
    )

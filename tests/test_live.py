"""Opt-in live-network smoke tests (deselected by default).

Run with:  pytest -m live
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.live


def test_live_cheap_and_impersonate_fetch():
    from kewpie.escalation.ladder import EscalatingFetcher
    f = EscalatingFetcher()
    try:
        r = f.fetch("https://example.com", max_tier="impersonate")
        assert r.ok
        assert "Example Domain" in r.text
    finally:
        f.close()


def test_live_hn_rss_collect_and_extract(tmp_path):
    from kewpie.pipeline import collect, extract
    (tmp_path / "s.json").write_text(json.dumps({
        "defaults": {"rate_limit_per_second": 1.0},
        "sources": [{"type": "rss", "id": "hn",
                     "url": "https://news.ycombinator.com/rss",
                     "fetch_full_article": False}],
    }))
    (tmp_path / "v.json").write_text(json.dumps({
        "proximity_chars": 300, "min_term_len": 4,
        "entities": {"source": "inline", "id_field": "id",
                     "name_fields": ["full_name"], "extra_fields": [],
                     "items": [{"id": 1, "full_name": "Google"}]},
        "signals": {"any": {"class": "info", "patterns": ["the", "a", "to"]}},
    }))
    c = collect(sources=tmp_path / "s.json", out_dir=tmp_path / "raw",
                state=tmp_path / "state", max_items=20)
    assert c["documents"] > 0
    e = extract(vocab=tmp_path / "v.json", raw_dir=tmp_path / "raw",
                out_dir=tmp_path / "sig")
    assert e["documents"] > 0

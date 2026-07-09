"""Tests for stores, config loading, and models."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from kewpie.config.loader import load_sources_config
from kewpie.extraction.vocabulary import load_vocabulary
from kewpie.models import FetchResult, RawDocument, Verdict
from kewpie.store.raw_store import append_raw, load_raw
from kewpie.store.signal_store import load_signals, write_signals


def _doc(url, title="t"):
    return RawDocument(url=url, source_id="s", source_name="S",
                       source_type="rss", title=title,
                       collected_at_utc=datetime.now(timezone.utc))


def test_raw_store_append_dedup(tmp_path):
    append_raw([_doc("https://x/1"), _doc("https://x/2")], tmp_path)
    append_raw([_doc("https://x/2", title="updated")], tmp_path)
    df = load_raw(tmp_path)
    assert len(df) == 2  # deduped by url
    assert df[df.url == "https://x/2"].iloc[0]["title"] == "updated"


def test_signal_store_legacy_column_map(tmp_path):
    df = pd.DataFrame([{"entity_id": 1, "entity_name": "X", "signal": "injury"}])
    write_signals(df, tmp_path,
                  legacy_column_map={"entity_id": "player_id",
                                     "entity_name": "full_name"})
    out = load_signals(tmp_path)
    assert "player_id" in out.columns and "full_name" in out.columns
    assert "entity_id" not in out.columns


def test_packaged_configs_load():
    defaults, sources = load_sources_config()
    assert isinstance(sources, list) and len(sources) >= 1
    types = {s.get("type") for s in sources}
    assert {"rss", "web", "reddit", "x", "newsapi"} <= types
    vocab = load_vocabulary()
    assert vocab.proximity_chars > 0 and vocab.signals


def test_fetchresult_ok_semantics():
    assert FetchResult("u", "u", 200, "", b"", {}).ok is True
    assert FetchResult("u", "u", 304, "", b"", {}).ok is True
    assert FetchResult("u", "u", 500, "", b"", {}).ok is False
    r = FetchResult("u", "u", 200, "", b"", {}, verdict=Verdict(blocked=True))
    assert r.ok is False


def test_rawdocument_requires_source_fields():
    with pytest.raises(Exception):
        RawDocument(url="u")  # missing required source fields

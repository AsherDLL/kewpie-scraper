"""Tests for HTML extraction and vocabulary signal extraction."""
from __future__ import annotations

import pandas as pd

from kewpie.extraction.html import extract
from kewpie.extraction.vocabulary import (
    VocabularyConfig, build_entity_index, extract_signals,
)


def _cfg(**over):
    base = dict(proximity_chars=120, min_term_len=5,
                signals={"injury": ("risk", ("injur", "ruled out")),
                         "motm": ("boost", ("player of the match",))})
    base.update(over)
    return VocabularyConfig(**base)


def _entities():
    return pd.DataFrame([
        {"id": 1, "full_name": "Ousmane Dembele", "surname": "Dembele", "team": "FRA"},
        {"id": 2, "full_name": "Orlando Gill", "surname": "Gill", "team": "PAR"},
    ])


def _spec():
    return {"id_field": "id", "name_fields": ["full_name", "surname"],
            "extra_fields": ["team"]}


def _docs(title, summary="", body=""):
    return pd.DataFrame([{"title": title, "summary": summary, "body_text": body,
                          "url": "http://x/a", "source_id": "s",
                          "source_confidence": 0.5, "published_at_utc": None,
                          "collected_at_utc": None}])


def test_html_extract_body_and_title():
    html = ("<html lang='en'><head><title>My Article</title></head><body>"
            "<article><p>" + "word " * 30 + "</p></article></body></html>")
    doc = extract(html)
    assert doc.title == "My Article"
    assert "word" in doc.body_text and doc.lang == "en"


def test_signal_fires_near_name():
    idx = build_entity_index(_entities(), _spec(), 5)
    out = extract_signals(_docs("Dembele suffers hamstring injury"), idx, _cfg())
    assert len(out) == 1
    assert out.iloc[0]["entity_name"] == "Ousmane Dembele"
    assert out.iloc[0]["signal"] == "injury" and out.iloc[0]["team"] == "FRA"


def test_no_signal_when_far_apart():
    body = "Dembele played well. " + ("x" * 400) + " injury news elsewhere."
    out = extract_signals(_docs("Report", body=body), build_entity_index(
        _entities(), _spec(), 5), _cfg())
    assert len(out) == 0


def test_accent_insensitive_match():
    ents = pd.DataFrame([{"id": 3, "full_name": "Kylian Mbappe", "surname": "Mbappe",
                          "team": "FRA"}])
    idx = build_entity_index(ents, {"id_field": "id",
                                    "name_fields": ["full_name", "surname"],
                                    "extra_fields": []}, 5)
    out = extract_signals(_docs("Mbappé named player of the match"), idx, _cfg())
    assert len(out) == 1 and out.iloc[0]["signal"] == "motm"


def test_short_surname_requires_full_name():
    idx = build_entity_index(_entities(), _spec(), 5)
    # "Gill" (4 < 5) must not fire on a town name.
    assert len(extract_signals(_docs("Gillingham injury crisis"), idx, _cfg())) == 0
    # Full name still matches.
    out = extract_signals(_docs("Orlando Gill injury scare"), idx, _cfg())
    assert len(out) == 1 and out.iloc[0]["entity_name"] == "Orlando Gill"

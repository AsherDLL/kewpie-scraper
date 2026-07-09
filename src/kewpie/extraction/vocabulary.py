"""Config-driven vocabulary extraction over stored raw documents.

Turns a corpus of collected documents into a structured (entity, document,
signal) table using a vocabulary file. A signal fires when a pattern and an
entity-name mention occur within ``proximity_chars`` of each other. Proximity
is the false-positive guard: a keyword in paragraph one and an entity in
paragraph nine is noise. Short entity names (below ``min_term_len``) must match
a full name variant to avoid substring hits.

The code has no hardcoded words: swap ``vocabulary.json`` and the entity source
and the same extractor works in any domain. This is a separate, cheap,
re-runnable stage over stored raw content, decoupled from collection.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "vocabulary.example.json"


@dataclass(frozen=True)
class VocabularyConfig:
    proximity_chars: int
    min_term_len: int
    signals: dict[str, tuple[str, tuple[str, ...]]]  # name -> (class, patterns)
    entities: dict = field(default_factory=dict)
    prefilter_default: Optional[dict] = None


def load_vocabulary(path: Path | str | None = None) -> VocabularyConfig:
    p = Path(path or os.environ.get("KEWPIE_VOCAB_CONFIG") or DEFAULT_CONFIG_PATH)
    raw = json.loads(p.read_text())
    signals = {
        name: (spec.get("class", "info"),
               tuple(s.lower() for s in spec.get("patterns", ())))
        for name, spec in raw.get("signals", {}).items()
    }
    return VocabularyConfig(
        proximity_chars=int(raw.get("proximity_chars", 220)),
        min_term_len=int(raw.get("min_term_len", raw.get("min_lastname_len", 5))),
        signals=signals,
        entities=raw.get("entities", {}),
        prefilter_default=raw.get("prefilter_default"),
    )


def _norm(text: str) -> str:
    """Lowercase, strip accents. Keeps offsets ~aligned (1 char per char)."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c if not unicodedata.combining(c) else " "
                       for c in decomposed)
    return stripped.lower()


def load_entities(spec: dict) -> pd.DataFrame:
    """Materialize the entity table from an inline list or a parquet/csv path."""
    source = spec.get("source", "inline")
    if source == "inline":
        return pd.DataFrame(spec.get("items", []))
    path = spec.get("path")
    if not path:
        raise ValueError(f"entities.source={source!r} requires 'path'")
    if source == "parquet":
        matches = sorted(Path().glob(path)) if any(c in path for c in "*?[") \
            else [Path(path)]
        if not matches:
            raise FileNotFoundError(f"no parquet matched {path!r}")
        return pd.read_parquet(matches[-1])
    if source == "csv":
        return pd.read_csv(path)
    raise ValueError(f"unknown entities.source: {source!r}")


def build_entity_index(entities: pd.DataFrame, spec: dict,
                       min_term_len: int) -> list[dict]:
    """One entry per entity with normalized name variants to search.

    The first ``name_fields`` entry is the primary name and is always searched;
    the remaining ones are searched only when long enough to be unambiguous.
    """
    name_fields = spec.get("name_fields", ["full_name"])
    id_field = spec.get("id_field", "entity_id")
    extra_fields = spec.get("extra_fields", [])
    primary = name_fields[0]
    index = []
    for _, row in entities.iterrows():
        variants: set[str] = set()
        primary_val = row.get(primary)
        if pd.isna(primary_val) or not str(primary_val):
            continue
        variants.add(_norm(str(primary_val)))
        for f in name_fields[1:]:
            v = row.get(f)
            if pd.notna(v) and len(str(v)) >= min_term_len:
                variants.add(_norm(str(v)))
        index.append({
            "entity_id": row.get(id_field),
            "entity_name": str(primary_val),
            "extra": {f: (None if pd.isna(row.get(f)) else row.get(f))
                      for f in extra_fields},
            "patterns": [re.compile(r"\b" + re.escape(v) + r"\b")
                         for v in variants if v],
        })
    return index


def extract_signals(documents: pd.DataFrame, entity_index: list[dict],
                    cfg: VocabularyConfig) -> pd.DataFrame:
    """One output row per (entity, document, signal) proximity hit."""
    rows = []
    for _, doc in documents.iterrows():
        text = " ".join(str(doc.get(c) or "") for c in
                        ("title", "summary", "body_text"))
        if len(text) < 20:
            continue
        norm = _norm(text)
        sig_hits: dict[str, list[int]] = {}
        for name, (cls, patterns) in cfg.signals.items():
            positions = [m.start() for pat in patterns
                         for m in re.finditer(re.escape(pat), norm)]
            if positions:
                sig_hits[name] = positions
        if not sig_hits:
            continue
        for entry in entity_index:
            name_positions = [m.start() for pat in entry["patterns"]
                              for m in pat.finditer(norm)]
            if not name_positions:
                continue
            for sig_name, positions in sig_hits.items():
                near = min((abs(sp - np_) for sp in positions
                            for np_ in name_positions), default=None)
                if near is None or near > cfg.proximity_chars:
                    continue
                cls = cfg.signals[sig_name][0]
                sp = min(positions,
                         key=lambda s: min(abs(s - n) for n in name_positions))
                lo = max(0, sp - 90)
                evidence = text[lo:sp + 130].strip().replace("\n", " ")
                row = {
                    "entity_id": entry["entity_id"],
                    "entity_name": entry["entity_name"],
                    "signal": sig_name,
                    "signal_class": cls,
                    "proximity_chars": int(near),
                    "evidence": evidence[:220],
                    "title": str(doc.get("title", ""))[:200],
                    "url": doc.get("url"),
                    "source_id": doc.get("source_id"),
                    "source_confidence": doc.get("source_confidence"),
                    "published_at_utc": doc.get("published_at_utc"),
                    "collected_at_utc": doc.get("collected_at_utc"),
                }
                row.update(entry["extra"])
                rows.append(row)
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(["signal_class", "signal", "entity_name"])
    return out

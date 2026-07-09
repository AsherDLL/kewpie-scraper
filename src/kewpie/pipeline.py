"""High-level collect and extract entry points.

``collect`` runs every configured source once and stores raw documents.
``extract`` runs the vocabulary stage over stored raw content and writes a
signal table. They are deliberately decoupled: extract can be re-run any number
of times without re-fetching.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .config.loader import load_sources_config, state_dir
from .escalation.ladder import EscalatingFetcher
from .extraction.vocabulary import (
    build_entity_index, extract_signals, load_entities, load_vocabulary,
)
from .sources.base import CollectContext
from .sources.conditional import ConditionalStore
from .sources.errors import SourceError
from .sources.registry import build_adapter
from .store.raw_store import DEFAULT_DIR as RAW_DEFAULT
from .store.raw_store import append_raw, enforce_budget, load_raw
from .store.signal_store import DEFAULT_DIR as SIG_DEFAULT
from .store.signal_store import write_signals

log = logging.getLogger(__name__)


def collect(*, sources=None, out_dir=None, state=None, max_items: int = 25,
            since_hours: float | None = None, prefilter: bool = False,
            vocab=None, cassette_mode: str = "off",
            max_tier: str | None = None) -> dict:
    defaults, source_cfgs = load_sources_config(sources)
    st = state_dir(state)
    fetcher = EscalatingFetcher(
        cache_dir=st / "cache",
        cache_ttl_hours=float(defaults.get("cache_ttl_hours", 6)),
        cassette_mode=cassette_mode,
        rate_limit_per_second=float(defaults.get("rate_limit_per_second", 0.5)),
        user_agent_contact=defaults.get("user_agent_contact"),
        max_tier=max_tier or defaults.get("max_tier", "browser"),
        state_dir=st,
    )
    conditional = ConditionalStore(st / "conditional.json")
    prefilter_default = None
    if prefilter:
        prefilter_default = load_vocabulary(vocab).prefilter_default
    ctx = CollectContext(
        fetcher=fetcher, conditional=conditional, defaults=defaults,
        prefilter_default=prefilter_default, max_items=max_items,
        since_hours=since_hours, force_prefilter=prefilter,
    )

    out = Path(out_dir or RAW_DEFAULT)
    per_source: dict[str, object] = {}
    total = 0
    for cfg in source_cfgs:
        sid = cfg.get("id") or cfg.get("type", "?")
        try:
            adapter = build_adapter(cfg, ctx)
            docs = list(adapter.collect() or [])
            if docs:
                append_raw(docs, out)
            per_source[sid] = len(docs)
            total += len(docs)
            log.info("source %s: %d documents", sid, len(docs))
        except SourceError as e:
            per_source[sid] = f"skipped:{type(e).__name__}"
            log.warning("source %s skipped: %s", sid, e)
        except Exception as e:  # noqa: BLE001
            per_source[sid] = "error"
            log.warning("source %s failed: %s", sid, e)

    try:
        fetcher.close()
    except Exception:  # noqa: BLE001
        pass
    budget = defaults.get("budget_mb")
    if budget:
        enforce_budget(float(budget), out)
    return {"sources": len(source_cfgs), "documents": total,
            "per_source": per_source, "out_dir": str(out)}


def extract(*, vocab=None, raw_dir=None, out_dir=None,
            since_days: float | None = None,
            legacy_column_map: dict | None = None) -> dict:
    cfg = load_vocabulary(vocab)
    entities = load_entities(cfg.entities)
    index = build_entity_index(entities, cfg.entities, cfg.min_term_len)
    docs = load_raw(Path(raw_dir or RAW_DEFAULT), since_days)
    if docs.empty:
        log.info("no raw documents found under %s", raw_dir or RAW_DEFAULT)
        return {"documents": 0, "signals": 0, "path": None}
    df = extract_signals(docs, index, cfg)
    path = write_signals(df, Path(out_dir or SIG_DEFAULT), legacy_column_map)
    log.info("%d signals from %d documents -> %s", len(df), len(docs), path)
    return {"documents": len(docs), "signals": len(df), "path": str(path)}

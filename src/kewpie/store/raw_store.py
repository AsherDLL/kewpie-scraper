"""Persist RawDocument rows as day-partitioned parquet with a disk budget.

One parquet file per UTC day. Rows are deduplicated by URL (keeping the most
recently collected). An overall byte budget prunes the oldest day before a run
grows the store past the cap.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..models import RawDocument

DEFAULT_DIR = Path("data/raw_docs")


def _today_path(out_dir: Path) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return out_dir / f"raw_{today}.parquet"


def append_raw(docs: Iterable[RawDocument], out_dir: Path = DEFAULT_DIR) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _today_path(out_dir)
    rows = [d.model_dump() for d in docs]
    new_df = pd.DataFrame(rows)
    if new_df.empty:
        return path
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    if "collected_at_utc" in combined.columns and "url" in combined.columns:
        combined = combined.sort_values("collected_at_utc").drop_duplicates(
            "url", keep="last")
    combined.to_parquet(path, index=False)
    return path


def disk_usage_bytes(out_dir: Path = DEFAULT_DIR) -> int:
    out_dir = Path(out_dir)
    if not out_dir.exists():
        return 0
    return sum(p.stat().st_size for p in out_dir.glob("raw_*.parquet"))


def prune_oldest(out_dir: Path = DEFAULT_DIR) -> Path | None:
    files = sorted(Path(out_dir).glob("raw_*.parquet"))
    if not files:
        return None
    oldest = files[0]
    oldest.unlink()
    return oldest


def enforce_budget(budget_mb: float, out_dir: Path = DEFAULT_DIR) -> int:
    """Prune oldest days until under budget. Returns files pruned."""
    cap = budget_mb * 1024 * 1024
    pruned = 0
    while disk_usage_bytes(out_dir) > cap:
        if prune_oldest(out_dir) is None:
            break
        pruned += 1
    return pruned


def load_raw(out_dir: Path = DEFAULT_DIR,
             since_days: float | None = None) -> pd.DataFrame:
    out_dir = Path(out_dir)
    if not out_dir.exists():
        return pd.DataFrame()
    frames = []
    for p in sorted(out_dir.glob("raw_*.parquet")):
        try:
            frames.append(pd.read_parquet(p))
        except (OSError, ValueError):
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if since_days is not None and "collected_at_utc" in df.columns:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=since_days)
        df["collected_at_utc"] = pd.to_datetime(df["collected_at_utc"], utc=True)
        df = df[df["collected_at_utc"] >= cutoff]
    return df

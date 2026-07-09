"""Persist extracted-signal tables as timestamped parquet.

Supports an optional legacy column map so a downstream project that expects
specific column names (e.g. a prior in-tree schema) gets byte-identical output
without changing the generic extractor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_DIR = Path("data/signals")


def write_signals(df: pd.DataFrame, out_dir: Path = DEFAULT_DIR,
                  legacy_column_map: dict | None = None) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if legacy_column_map:
        df = df.rename(columns=legacy_column_map)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    path = out_dir / f"signals_{ts}.parquet"
    df.to_parquet(path, index=False)
    return path


def load_signals(out_dir: Path = DEFAULT_DIR) -> pd.DataFrame:
    out_dir = Path(out_dir)
    if not out_dir.exists():
        return pd.DataFrame()
    frames = []
    for p in sorted(out_dir.glob("signals_*.parquet")):
        try:
            frames.append(pd.read_parquet(p))
        except (OSError, ValueError):
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

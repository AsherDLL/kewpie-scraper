"""Config resolution for sources and runtime state.

Resolution order for the sources file: explicit path -> KEWPIE_SOURCES_CONFIG
env -> packaged example. The vocabulary file is resolved the same way inside
``kewpie.extract.load_vocabulary`` (KEWPIE_VOCAB_CONFIG). Runtime state (cache,
learned policy, conditional-GET validators) lives under KEWPIE_STATE_DIR.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_SOURCES_PATH = Path(__file__).resolve().parent / "sources.example.json"
DEFAULT_VOCAB_PATH = Path(__file__).resolve().parent / "vocabulary.example.json"


def resolve_sources_path(explicit: Path | str | None = None) -> Path:
    return Path(explicit or os.environ.get("KEWPIE_SOURCES_CONFIG")
                or DEFAULT_SOURCES_PATH)


def load_sources_config(path: Path | str | None = None) -> tuple[dict, list[dict]]:
    """Return (defaults, sources) from the sources config file."""
    p = resolve_sources_path(path)
    raw = json.loads(Path(p).read_text())
    return raw.get("defaults", {}), raw.get("sources", [])


def state_dir(explicit: Path | str | None = None) -> Path:
    return Path(explicit or os.environ.get("KEWPIE_STATE_DIR") or ".kewpie_state")

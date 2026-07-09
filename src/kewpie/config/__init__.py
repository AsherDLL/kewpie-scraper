"""Config loading (sources.json / vocabulary.json) and state-dir resolution."""
from __future__ import annotations

from .loader import (
    DEFAULT_SOURCES_PATH, DEFAULT_VOCAB_PATH, load_sources_config,
    resolve_sources_path, state_dir,
)

__all__ = [
    "load_sources_config", "resolve_sources_path", "state_dir",
    "DEFAULT_SOURCES_PATH", "DEFAULT_VOCAB_PATH",
]

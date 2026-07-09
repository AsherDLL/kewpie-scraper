"""Extraction: HTML article parsing + vocabulary signal extraction."""
from __future__ import annotations

from .html import extract
from .vocabulary import (
    VocabularyConfig, build_entity_index, extract_signals, load_entities,
    load_vocabulary,
)

__all__ = [
    "extract",
    "VocabularyConfig", "load_vocabulary", "load_entities",
    "build_entity_index", "extract_signals",
]

"""Reusability demo: Kewpie on a NON-football domain, no code changes.

Collects Hacker News headlines and extracts tech-company signals purely from
config. This is the whole point of Kewpie: swap sources.json + vocabulary.json
and the same engine works for any domain.

    python examples/reusability_demo.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from kewpie.pipeline import collect, extract

SOURCES = {
    "defaults": {
        "rate_limit_per_second": 1.0,
        "user_agent_contact": "kewpie-demo (+https://github.com/AsherDLL/kewpie-crawler)",
        "max_tier": "impersonate",
    },
    "sources": [
        {"type": "rss", "id": "hackernews", "name": "Hacker News",
         "url": "https://news.ycombinator.com/rss", "fetch_full_article": False},
    ],
}

VOCABULARY = {
    "proximity_chars": 300,
    "min_term_len": 4,
    "entities": {
        "source": "inline", "id_field": "id", "name_fields": ["full_name"],
        "extra_fields": [],
        "items": [
            {"id": 1, "full_name": "Google"}, {"id": 2, "full_name": "Apple"},
            {"id": 3, "full_name": "Microsoft"}, {"id": 4, "full_name": "OpenAI"},
            {"id": 5, "full_name": "Amazon"}, {"id": 6, "full_name": "Meta"},
        ],
    },
    "signals": {
        "launch": {"class": "info",
                   "patterns": ["launch", "release", "announces", "introduc", "unveil"]},
        "security": {"class": "risk",
                     "patterns": ["vulnerability", "breach", "exploit", "hacked", "outage"]},
    },
}


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="kewpie-demo-"))
    (work / "sources.json").write_text(json.dumps(SOURCES))
    (work / "vocabulary.json").write_text(json.dumps(VOCABULARY))

    collected = collect(sources=work / "sources.json", out_dir=work / "raw",
                        state=work / "state", max_items=30)
    print("collected:", json.dumps(collected, indent=2))

    extracted = extract(vocab=work / "vocabulary.json", raw_dir=work / "raw",
                       out_dir=work / "signals")
    print("extracted:", json.dumps(extracted, indent=2))
    print(f"\nRaw docs + signals written under: {work}")


if __name__ == "__main__":
    main()

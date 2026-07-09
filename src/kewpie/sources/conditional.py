"""Per-URL conditional-GET state (ETag / Last-Modified).

Persisting validators lets us send If-None-Match / If-Modified-Since so a
server can answer 304 Not Modified instead of resending an unchanged feed.
This is mandatory etiquette for RSS polling and cuts bandwidth for everyone.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path


class ConditionalStore:
    def __init__(self, path: Path | str | None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path or not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def headers_for(self, url: str) -> dict[str, str]:
        with self._lock:
            e = self._data.get(url) or {}
        h: dict[str, str] = {}
        if e.get("etag"):
            h["If-None-Match"] = e["etag"]
        if e.get("last_modified"):
            h["If-Modified-Since"] = e["last_modified"]
        return h

    def update(self, url: str, response_headers: dict) -> None:
        lower = {k.lower(): v for k, v in (response_headers or {}).items()}
        etag = lower.get("etag")
        last_mod = lower.get("last-modified")
        if not etag and not last_mod:
            return
        with self._lock:
            self._data[url] = {"etag": etag, "last_modified": last_mod}
            self._save_locked()

    def _save_locked(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
            tmp.replace(self.path)
        except OSError:
            pass

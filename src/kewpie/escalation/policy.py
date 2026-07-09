"""Per-host learned tier policy.

Remembers, per host, which ladder tier last worked, so the next fetch starts
there instead of re-climbing from the cheapest tier every time. Periodically it
probes one tier lower (WAF posture relaxes over time), so a host never gets
stuck permanently on the expensive browser tier.

State is a small JSON file, written atomically, guarded by a lock.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

# Default: probe one tier lower at most once every 6 hours per host.
DEFAULT_PROBE_INTERVAL_S = 6 * 3600


class PerHostPolicyStore:
    def __init__(self, path: Path | str | None,
                 max_tier_index: int = 2,
                 probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S):
        self.path = Path(path) if path else None
        self.max_tier_index = max_tier_index
        self.probe_interval_s = probe_interval_s
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

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
            tmp.replace(self.path)
        except OSError:
            pass

    def start_tier(self, host: str) -> int:
        """The tier to begin at for this host (0 by default).

        If the stored tier is above the cheapest and the probe interval has
        elapsed, return one tier lower once to test whether the host relaxed.
        """
        with self._lock:
            e = self._data.get(host)
            if not e:
                return 0
            tier = int(e.get("tier", 0))
            if tier > 0 and (time.time() - float(e.get("last_probe", 0.0))
                             > self.probe_interval_s):
                e["last_probe"] = time.time()
                self._save()
                return tier - 1
            return tier

    def record(self, host: str, tier: int, ok: bool,
               vendor: str | None = None) -> None:
        with self._lock:
            e = self._data.setdefault(host, {
                "tier": 0, "vendor": None, "successes": 0,
                "failures": 0, "updated_at": 0.0, "last_probe": 0.0,
            })
            if ok:
                e["tier"] = int(tier)
                e["successes"] = int(e.get("successes", 0)) + 1
            else:
                e["failures"] = int(e.get("failures", 0)) + 1
                # Remember we needed at least the next tier up.
                e["tier"] = min(self.max_tier_index,
                                max(int(e.get("tier", 0)), int(tier) + 1))
            if vendor:
                e["vendor"] = vendor
            e["updated_at"] = time.time()
            self._save()

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return json.loads(json.dumps(self._data))

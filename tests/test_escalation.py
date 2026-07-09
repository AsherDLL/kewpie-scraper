"""Tests for the escalation ladder and the learned policy."""
from __future__ import annotations

from kewpie.escalation.ladder import EscalatingFetcher
from kewpie.escalation.policy import PerHostPolicyStore
from kewpie.models import FetchResult


class FakeTier:
    def __init__(self, name, status, body, headers=None, avail=True):
        self.name = name
        self._s, self._b = status, body
        self._h = headers or {"content-type": "text/html"}
        self._avail = avail
        self.calls = 0

    def available(self):
        return self._avail

    def fetch(self, url, **kw):
        self.calls += 1
        return FetchResult(url=url, final_url=url, status_code=self._s,
                           text=self._b, content=self._b.encode(),
                           headers=self._h, tier=self.name)


_REAL = "<html>" + "<p>real content that is definitely long enough</p>" * 20 + "</html>"


def _ladder(tmp_path, tiers, max_tier="browser"):
    f = EscalatingFetcher(state_dir=tmp_path, browser_backend=None,
                          max_tier=max_tier)
    f._tiers = tiers
    return f


def test_escalates_past_block(tmp_path):
    cheap = FakeTier("cheap", 403, "<title>just a moment</title>",
                     {"cf-mitigated": "challenge", "content-type": "text/html"})
    imp = FakeTier("impersonate", 200, _REAL)
    brow = FakeTier("browser", 200, "<html>rendered</html>")
    f = _ladder(tmp_path, [cheap, imp, brow])
    r = f.fetch("https://ex.com/a")
    assert r.tier == "impersonate"
    assert cheap.calls == 1 and imp.calls == 1 and brow.calls == 0


def test_stops_at_first_ok(tmp_path):
    cheap = FakeTier("cheap", 200, _REAL)
    imp = FakeTier("impersonate", 200, _REAL)
    f = _ladder(tmp_path, [cheap, imp, FakeTier("browser", 200, "x")])
    r = f.fetch("https://ex.com/a")
    assert r.tier == "cheap" and imp.calls == 0


def test_respects_max_tier_cap(tmp_path):
    cheap = FakeTier("cheap", 403, "just a moment",
                     {"cf-mitigated": "challenge", "content-type": "text/html"})
    imp = FakeTier("impersonate", 403, "just a moment",
                   {"cf-mitigated": "challenge", "content-type": "text/html"})
    brow = FakeTier("browser", 200, _REAL)
    f = _ladder(tmp_path, [cheap, imp, brow], max_tier="impersonate")
    r = f.fetch("https://ex.com/a")
    # Capped at impersonate: never reaches browser even though both blocked.
    assert brow.calls == 0
    assert r.tier == "impersonate"


def test_skips_unavailable_browser(tmp_path):
    cheap = FakeTier("cheap", 403, "just a moment",
                     {"cf-mitigated": "challenge", "content-type": "text/html"})
    imp = FakeTier("impersonate", 403, "just a moment",
                   {"cf-mitigated": "challenge", "content-type": "text/html"})
    brow = FakeTier("browser", 200, _REAL, avail=False)
    f = _ladder(tmp_path, [cheap, imp, brow])
    r = f.fetch("https://ex.com/a")
    assert brow.calls == 0  # unavailable
    assert r.tier == "impersonate"  # best effort


def test_learned_policy_starts_higher(tmp_path):
    cheap = FakeTier("cheap", 403, "just a moment",
                     {"cf-mitigated": "challenge", "content-type": "text/html"})
    imp = FakeTier("impersonate", 200, _REAL)
    f = _ladder(tmp_path, [cheap, imp, FakeTier("browser", 200, "x")])
    f.fetch("https://ex.com/a")
    # Disable probing so the learned tier is used directly.
    f.policy.probe_interval_s = 10 ** 12
    cheap.calls = imp.calls = 0
    r = f.fetch("https://ex.com/b")
    assert r.tier == "impersonate" and cheap.calls == 0


def test_policy_probe_ratchets_down(tmp_path):
    p = PerHostPolicyStore(tmp_path / "policy.json", probe_interval_s=0)
    p.record("h", 1, ok=True)
    # Probe interval 0 -> immediately probe one lower.
    assert p.start_tier("h") == 0


def test_policy_no_probe_when_interval_large(tmp_path):
    p = PerHostPolicyStore(tmp_path / "policy.json", probe_interval_s=10 ** 12)
    p.record("h", 2, ok=True)
    assert p.start_tier("h") == 2

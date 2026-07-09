"""Tests for the engine primitives: cache, rate limiter, retry, proxies."""
from __future__ import annotations


import pytest

from kewpie.engine.cache import DiskCache
from kewpie.engine.identity import (
    load_identity_map, pick_for_host, save_identity_map,
)
from kewpie.engine.proxies import ProxyConfig, ProxyRotator
from kewpie.engine.rate_limit import PerHostRateLimiter
from kewpie.engine.retry import retry_with_backoff


def test_cache_round_trip_and_ttl(tmp_path):
    c = DiskCache(tmp_path, ttl_hours=6)
    c.put("GET", "https://x/a", None, b"body", 200, {"h": "1"})
    hit = c.get("GET", "https://x/a")
    assert hit is not None and hit.body == b"body" and hit.status_code == 200
    # Expired TTL -> miss.
    c0 = DiskCache(tmp_path, ttl_hours=0)
    assert c0.get("GET", "https://x/a") is None


def test_cache_cassette_replay(tmp_path):
    rec = DiskCache(tmp_path, mode="record")
    rec.put("GET", "https://x/a", None, b"cassette", 200, {})
    replay = DiskCache(tmp_path, ttl_hours=0, mode="replay")
    # Replay ignores TTL and serves the stored entry.
    hit = replay.get("GET", "https://x/a")
    assert hit is not None and hit.body == b"cassette"
    # Replay never writes.
    replay.put("GET", "https://x/b", None, b"new", 200, {})
    assert replay.get("GET", "https://x/b") is None


def test_rate_limiter_enforces_min_interval():
    rl = PerHostRateLimiter(requests_per_second=20)  # 50ms min interval
    rl.acquire("https://host/a")
    slept = rl.acquire("https://host/a")
    assert slept > 0
    # Different host is independent.
    assert rl.acquire("https://other/a") == 0.0


def test_rate_limiter_rejects_nonpositive():
    with pytest.raises(ValueError):
        PerHostRateLimiter(0)


def test_retry_succeeds_after_transient():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    out = retry_with_backoff(flaky, max_attempts=3, base_delay_s=0.001,
                             is_retryable=lambda e: isinstance(e, ConnectionError))
    assert out == "ok" and calls["n"] == 3


def test_retry_result_predicate():
    seq = iter([1, 1, 42])
    out = retry_with_backoff(lambda: next(seq), max_attempts=3, base_delay_s=0.001,
                             is_retryable=lambda v: v == 1)
    assert out == 42


def test_identity_pick_is_deterministic():
    a = pick_for_host("example.com")
    b = pick_for_host("example.com")
    assert a.name == b.name


def test_identity_map_persistence(tmp_path):
    p = tmp_path / "ids.json"
    save_identity_map(p, {"example.com": 2})
    assert load_identity_map(p) == {"example.com": 2}
    assert load_identity_map(tmp_path / "missing.json") == {}


def test_proxy_pairing_is_deterministic():
    pool = [ProxyConfig(url=f"http://p{i}") for i in range(4)]
    rot = ProxyRotator(pool, mode="random")
    a = rot.pick_for("example.com", 1)
    b = rot.pick_for("example.com", 1)
    assert a.url == b.url  # stable per (host, identity)
    assert ProxyRotator([]).pick_for("x", 0) is None

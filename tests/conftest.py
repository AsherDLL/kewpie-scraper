"""Shared test fixtures and fakes.

curl_cffi does not go through httpx, so we inject fake fetchers rather than
mock the transport. A FakeFetcher stands in for EscalatingFetcher and returns
canned FetchResults keyed by URL (or '*' as a catch-all).
"""
from __future__ import annotations

import pytest

from kewpie.models import FetchResult


def make_result(url: str, status: int = 200, text: str = "",
                headers: dict | None = None, content: bytes | None = None,
                tier: str = "impersonate") -> FetchResult:
    return FetchResult(
        url=url, final_url=url, status_code=status, text=text,
        content=content if content is not None else text.encode("utf-8"),
        headers=headers or {"content-type": "text/html"}, tier=tier,
    )


class FakeFetcher:
    """Stand-in for EscalatingFetcher used by source-adapter tests."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, url, *, want_body=True, max_tier=None, wait_for=None,
              headers=None, bypass_cache=False):
        self.calls.append(url)
        r = self.responses.get(url, self.responses.get("*"))
        if callable(r):
            r = r(url)
        if r is None:
            raise RuntimeError(f"no fake response registered for {url}")
        return r

    def close(self):
        pass


@pytest.fixture
def fake_fetcher_factory():
    def _factory(responses: dict) -> FakeFetcher:
        return FakeFetcher(responses)
    return _factory

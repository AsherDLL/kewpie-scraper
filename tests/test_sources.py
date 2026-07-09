"""Tests for the five source adapters (fake fetcher; no network)."""
from __future__ import annotations

import pytest
from conftest import FakeFetcher, make_result

from kewpie.sources.base import CollectContext
from kewpie.sources.conditional import ConditionalStore
from kewpie.sources.errors import AuthError
from kewpie.sources.newsapi import NewsApiSource
from kewpie.sources.reddit import RedditSource
from kewpie.sources.rss import RssSource
from kewpie.sources.x import XSource

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Player injury news</title><link>https://ex.com/a1</link>
<description>summary about an injury</description>
<pubDate>Wed, 08 Jul 2026 12:00:00 GMT</pubDate></item>
<item><title>Transfer rumor</title><link>https://ex.com/a2</link>
<description>summary two</description></item>
</channel></rss>"""


def _ctx(fetcher, **over):
    kw = dict(fetcher=fetcher, conditional=ConditionalStore(None), defaults={},
              prefilter_default=None, max_items=25, since_hours=None,
              force_prefilter=False)
    kw.update(over)
    return CollectContext(**kw)


def test_rss_parses_entries():
    feed = "https://ex.com/rss"
    fetcher = FakeFetcher({feed: make_result(feed, text=RSS,
                                             headers={"content-type": "application/rss+xml"})})
    ctx = _ctx(fetcher)
    docs = list(RssSource({"url": feed, "id": "t", "name": "T",
                           "fetch_full_article": False}, ctx).collect())
    assert len(docs) == 2
    assert {d.title for d in docs} == {"Player injury news", "Transfer rumor"}
    assert all(d.source_type == "rss" for d in docs)


def test_rss_prefilter_drops_nonmatching():
    feed = "https://ex.com/rss"
    fetcher = FakeFetcher({feed: make_result(feed, text=RSS)})
    ctx = _ctx(fetcher)
    docs = list(RssSource({"url": feed, "id": "t", "fetch_full_article": False,
                           "prefilter": {"enabled": True, "keywords": ["injury"],
                                         "fields": ["title", "summary"]}}, ctx).collect())
    assert len(docs) == 1 and "injury" in docs[0].title.lower()


def test_rss_304_yields_nothing():
    feed = "https://ex.com/rss"
    fetcher = FakeFetcher({feed: make_result(feed, status=304, text="")})
    ctx = _ctx(fetcher)
    docs = list(RssSource({"url": feed, "id": "t"}, ctx).collect())
    assert docs == []


_NEWS_JSON = ('{"status":"ok","articles":[{"url":"https://n/1","title":"Big news",'
              '"description":"desc","content":"body","publishedAt":"2026-07-08T00:00:00Z",'
              '"author":"A","source":{"name":"Src"}}]}')


def test_newsapi_maps_fields_and_query_auth(monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "secret123")
    fetcher = FakeFetcher({"*": lambda url: make_result(url, text=_NEWS_JSON,
                                                        headers={"content-type": "application/json"})})
    ctx = _ctx(fetcher)
    cfg = {"endpoint": "https://newsapi.org/v2/everything", "id": "n",
           "auth": {"mode": "query", "param": "apiKey", "key_env": "NEWSAPI_KEY"},
           "query_params": {"q": "x"}, "items_path": "articles",
           "ok_predicate": {"field": "status", "not_equals": "error"},
           "field_map": {"url": "url", "title": "title", "summary": "description",
                         "body": "content", "source_name": "source.name"}}
    docs = list(NewsApiSource(cfg, ctx).collect())
    assert len(docs) == 1 and docs[0].title == "Big news"
    assert "apiKey=secret123" in fetcher.calls[0]  # key placed in query string


def test_newsapi_missing_key_raises_autherror(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    fetcher = FakeFetcher({"*": lambda url: make_result(url, text="{}")})
    ctx = _ctx(fetcher)
    cfg = {"endpoint": "https://x/api", "auth": {"key_env": "NOPE_KEY"}}
    with pytest.raises(AuthError):
        list(NewsApiSource(cfg, ctx).collect())


def test_newsapi_200_with_error_body(monkeypatch):
    body = '{"status":"error","code":"apiKeyInvalid","message":"bad key"}'
    fetcher = FakeFetcher({"*": lambda url: make_result(url, text=body)})
    ctx = _ctx(fetcher)
    cfg = {"endpoint": "https://x/api", "items_path": "articles",
           "ok_predicate": {"field": "status", "not_equals": "error"}}
    with pytest.raises(AuthError):
        list(NewsApiSource(cfg, ctx).collect())


def test_reddit_rss_mode_builds_url():
    url = "https://www.reddit.com/r/soccer/new/.rss"
    fetcher = FakeFetcher({url: make_result(url, text=RSS)})
    ctx = _ctx(fetcher)
    docs = list(RedditSource({"subreddit": "soccer", "listing": "new",
                              "mode": "rss", "id": "r"}, ctx).collect())
    assert len(docs) == 2 and all(d.source_type == "reddit" for d in docs)


def test_reddit_arctic_shift_parses_json():
    fetcher = FakeFetcher({"*": lambda url: make_result(
        url, text='{"data":[{"title":"T","selftext":"body","permalink":"/r/x/1",'
                  '"created_utc":1700000000}]}')})
    ctx = _ctx(fetcher)
    cfg = {"subreddit": "x", "mode": "arctic_shift",
           "arctic_shift": {"endpoint": "https://arctic/api/posts/search"}}
    docs = list(RedditSource(cfg, ctx).collect())
    assert len(docs) == 1 and docs[0].title == "T"


def test_x_off_and_auto_without_creds():
    ctx = _ctx(FakeFetcher({}))
    assert list(XSource({"mode": "off"}, ctx).collect()) == []
    assert list(XSource({"mode": "auto"}, ctx).collect()) == []


def test_x_syndication_by_tweet_id():
    from kewpie.sources.x import _SYNDICATION
    url = _SYNDICATION.format(id="123")
    fetcher = FakeFetcher({url: make_result(
        url, text='{"text":"hello world","user":{"screen_name":"bob"},'
                  '"created_at":"2026-07-08T00:00:00Z"}',
        headers={"content-type": "application/json"})})
    ctx = _ctx(fetcher)
    docs = list(XSource({"mode": "syndication", "tweet_ids": ["123"]}, ctx).collect())
    assert len(docs) == 1 and docs[0].body_text == "hello world"

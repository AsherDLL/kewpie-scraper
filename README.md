# Kewpie Crawler

A reusable, anti-bot-resistant, config-driven content collector.

Kewpie fetches content the way a real browser does (matching TLS, HTTP/2, and
header fingerprints), escalates to a headless browser only when a site actually
challenges it, and keeps *what to fetch* and *what to look for* in JSON config so
the same engine works for any domain. Point it at a new set of sources and a new
vocabulary and it is a different collector, with no code changes.

Mascot: a Kewpie-doll figurine.

## Why it exists

A plain `requests`/`httpx` client is identified as a bot at the TLS handshake,
before its headers are even read. That is the "simple blocker" most home-grown
scrapers never get past. Kewpie's engine impersonates a real browser's TLS/JA3/JA4
and HTTP/2 fingerprint with coherent client-hint headers, so passive WAF
fingerprinting (Cloudflare, Akamai, DataDome at the fingerprint tier) sees a real
Chrome or Firefox. When a site serves an actual JavaScript challenge, Kewpie
escalates to a headless browser rather than pretending the challenge page is data.

Kewpie does not try to win a bypass arms race. It orchestrates best-of-breed
open-source tools (`curl_cffi` for impersonation, `nodriver`/`camoufox` for the
browser tier) and adds the orchestration layer that most scrapers lack.

## Install

```bash
pip install kewpie-crawler                 # HTTP tiers only (light)
pip install "kewpie-crawler[browser]"      # + headless nodriver escalation tier
pip install "kewpie-crawler[reddit]"       # + PRAW for the Reddit official API
pip install "kewpie-crawler[all]"          # everything
```

## Quickstart

```python
from kewpie import EscalatingFetcher

fetcher = EscalatingFetcher(cache_dir=".kewpie_state/cache")
result = fetcher.fetch("https://example.com/article")
print(result.tier, result.status_code, result.verdict.kind)
print(result.text[:500])
```

Config-driven collection over many sources:

```bash
kewpie collect --sources sources.json --out data/raw    # fetch -> raw documents
kewpie extract --vocab vocabulary.json --raw-dir data/raw --out data/signals
```

Diagnose your fingerprint before a run:

```bash
kewpie doctor            # asserts UA <-> Client-Hints <-> TLS <-> HTTP/2 cohere
kewpie fetch https://example.com --tier auto --json
```

## The escalation ladder

Kewpie runs three tiers and moves up only when the response is challenged:

| Tier | Backend | Handles |
|------|---------|---------|
| `cheap` | curl_cffi, no impersonation | RSS/JSON APIs, well-behaved hosts |
| `impersonate` | curl_cffi TLS impersonation + coherent identity | passive WAF fingerprint tier |
| `browser` | headless nodriver / Camoufox (optional extra) | JS challenges, Turnstile, hydration |

A structured challenge classifier decides when to escalate, based on status codes,
anti-bot cookies (`cf_clearance`, `datadome`, `_abck`, ...), challenge headers,
Turnstile/reCAPTCHA script markers, and tiny-HTML-shell / empty-extraction
heuristics. Kewpie remembers per host which tier worked and starts there next
time, and periodically probes one tier lower so it never gets stuck on the browser.

## Two config files

- **`sources.json`** - *where* to fetch. Five source types: `rss`, `web`,
  `reddit`, `x`, `newsapi`. The engine contains no URLs or API keys.
- **`vocabulary.json`** - *what* to look for. Entities plus signal patterns; drives
  a separate, cheap, re-runnable extraction stage over the stored raw content.

Collection stores raw content by default; extraction runs afterward and can be
re-run any number of times without re-fetching. A fetch-time keyword prefilter is
available per source for high-volume feeds, but it is off by default: filtering at
fetch time discards data you cannot get back without re-scraping.

See `src/kewpie/config/sources.example.json` and `vocabulary.example.json`.

## Escalation beyond Kewpie

Kewpie handles the passive-fingerprint tier and JS challenges its headless backend
can auto-clear. It deliberately does not solve CAPTCHAs or defeat behavioral or
heavily-obfuscated protection (Kasada, aggressive DataDome). When a site needs
that, the fetch result carries a `Verdict` naming the vendor and challenge kind so
you can route it to a dedicated solver. This is a design choice, not a gap:
hand-maintained bypasses break within days.

## Ethics

Kewpie ships with conservative defaults: robots.txt is honored, rate limits are
low, and it only reads public content. Prefer official APIs and RSS where they
exist. See the responsible-use notes in the source. You are responsible for
complying with each site's terms of service and the law in your jurisdiction.

## License

MIT. See `LICENSE`.

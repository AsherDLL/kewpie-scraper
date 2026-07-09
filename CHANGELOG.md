# Changelog

All notable changes to Kewpie Crawler are documented here. The format is loosely
based on Keep a Changelog, and the project follows semantic versioning.

## [0.1.0] - unreleased

Initial release.

### Added
- HTTP impersonation engine (`kewpie.engine`): `StealthClient` with curl_cffi
  TLS/JA3/JA4 impersonation, a coherent per-host identity pool, per-host rate
  limiting, a TTL disk cache with record-replay cassette mode, exponential
  backoff, and identity-per-proxy pairing.
- Structured challenge classifier (`kewpie.challenge.classify_challenge`)
  returning a `Verdict` (vendor, kind, confidence, evidence, escalate).
- Signal-driven escalation ladder (`kewpie.escalation`): cheap HTTP ->
  impersonation -> headless browser, with a persisted per-host learned policy.
- Optional headless browser backends (`kewpie.browser`): nodriver, Camoufox.
- Five config-driven ingestion modes (`kewpie.sources`): RSS, web, Reddit, X,
  and a generic news-API adapter.
- Re-runnable vocabulary extraction (`kewpie.extract`) over stored raw content.
- CLI: `kewpie collect | extract | doctor | fetch`.

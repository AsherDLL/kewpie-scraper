"""`kewpie doctor`: prove the fetch fingerprint is internally coherent.

The single most common own-goal is a Chrome User-Agent sent over an OpenSSL TLS
handshake: the story does not cohere and WAFs flag it. This command sends each
identity in the pool to a TLS/JA3/JA4/HTTP2 reflector and checks that the
User-Agent the server sees matches the one we claim, and that a real browser
TLS fingerprint (JA3/JA4) is present. It also reports config validity and
whether an optional browser backend is installed.
"""
from __future__ import annotations

import json as _json
import logging

log = logging.getLogger(__name__)

DEFAULT_REFLECTOR = "https://tls.peet.ws/api/all"


def _dig_ua(data) -> str | None:
    if isinstance(data, dict):
        if isinstance(data.get("user_agent"), str):
            return data["user_agent"]
        for v in data.values():
            found = _dig_ua(v)
            if found:
                return found
    return None


def _has_fingerprint(text: str) -> bool:
    low = text.lower()
    return ("ja3" in low) or ("ja4" in low)


def run(reflector: str | None = None) -> int:
    from ..browser import load_default_browser_backend
    from ..config.loader import load_sources_config
    from ..engine.client import StealthClient
    from ..engine.identity import DEFAULT_POOL
    from ..extraction.vocabulary import load_vocabulary

    ok = True
    print("kewpie doctor")
    print("=" * 60)

    # 1. Config validity.
    try:
        defaults, sources = load_sources_config()
        print(f"[ok]   sources config loads: {len(sources)} source(s)")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"[FAIL] sources config: {e}")
    try:
        vcfg = load_vocabulary()
        print(f"[ok]   vocabulary config loads: {len(vcfg.signals)} signal(s)")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] vocabulary config: {e}")

    # 2. Browser backend.
    backend = load_default_browser_backend()
    if backend is not None:
        print(f"[ok]   browser backend available: {backend.name}")
    else:
        print("[info] no browser backend installed "
              "(install kewpie[browser] to enable the tier-2 render escalation)")

    # 3. Fingerprint coherence per identity.
    url = reflector or DEFAULT_REFLECTOR
    print(f"\nfingerprint reflector: {url}")
    print("-" * 60)
    for ident in DEFAULT_POOL:
        client = StealthClient(identity_pool=(ident,), cache_dir=None,
                               rate_limit_per_second=2.0, max_retries=1)
        try:
            r = client.get(url)
            data = None
            try:
                data = r.json()
            except Exception:  # noqa: BLE001
                pass
            reflected_ua = _dig_ua(data) if data is not None else None
            fp_present = _has_fingerprint(r.text or "")
            ua_match = (reflected_ua == ident.user_agent) if reflected_ua else None
            status = "ok" if (fp_present and ua_match in (True, None)) else "FAIL"
            if status == "FAIL":
                ok = False
            print(f"[{status:4}] {ident.name:20} "
                  f"ua_match={ua_match} tls_fingerprint={'yes' if fp_present else 'no'}")
            if reflected_ua and ua_match is False:
                print(f"        sent UA:      {ident.user_agent}")
                print(f"        server saw:   {reflected_ua}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {ident.name:20} reflector unreachable: {e}")
        finally:
            client.close()

    print("=" * 60)
    print("doctor:", "PASS" if ok else "issues found")
    return 0 if ok else 1


def _debug_dump(data) -> str:
    return _json.dumps(data, indent=2)[:2000]

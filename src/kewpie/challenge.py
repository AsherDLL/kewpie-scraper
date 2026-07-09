"""WAF / anti-bot challenge classifier.

``classify_challenge`` inspects an HTTP response and returns a structured
``Verdict`` (vendor, kind, confidence, evidence, escalate). It is the single
source of truth the escalation ladder consults to decide whether to move up a
tier, and it is reusable on its own to tell real content from a challenge page.

Design note on false positives: some anti-bot cookies (``__cf_bm``,
``cf_clearance``, ``datadome``, ``_abck``, ``ak_bmsc``) are set on *normal*
traffic from a fronted site, so their mere presence is NOT a block. We only
treat unambiguous *active-challenge* signals as blocks: challenge headers,
challenge scripts in the body, the known interstitial body needles, AWS WAF's
202, and Cloudflare's ``cf_chl_*`` challenge cookie. Ambiguous cookies are
ignored on purpose.
"""
from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Mapping

from .models import ChallengeKind, Verdict

# Status codes worth retrying at the same tier (transient), re-exported for
# callers that want the engine's retry set without importing engine.retry.
RETRY_STATUSES = (408, 429, 500, 502, 503, 504)

# Body substrings that indicate a WAF / bot-management page rather than real
# content. Matched case-insensitively against the first 16 KB. Each maps to a
# (vendor, kind).
_BLOCK_BODY_NEEDLES: tuple[tuple[str, str, str], ...] = (
    ("cloudflare", "interstitial", "<title>just a moment"),
    ("cloudflare", "js_challenge", "challenge-platform/h/"),
    ("cloudflare", "js_challenge", "_cf_chl_opt"),
    ("cloudflare", "js_challenge", "window._cf_chl_ctx"),
    ("aws_waf", "js_challenge", "awswafintegration"),
    ("aws_waf", "js_challenge", "/aws-waf-token"),
    ("datadome", "captcha", "datadome.co/captcha"),
    ("datadome", "captcha", "geo.captcha-delivery.com"),
    ("akamai", "js_challenge", "ak_bmsc"),
    ("akamai", "js_challenge", "_abck"),
    ("perimeterx", "js_challenge", "perimeterx"),
    ("perimeterx", "js_challenge", "_pxhd"),
    ("imperva", "interstitial", "incapsula incident id"),
    ("kasada", "js_challenge", "kpsdk-cd"),
)

# Challenge-widget script markers -> (vendor, kind). Reliable: these only
# appear when an interactive challenge is being served.
_CHALLENGE_SCRIPT_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("cloudflare", "turnstile", "challenges.cloudflare.com/turnstile"),
    ("recaptcha", "captcha", "www.google.com/recaptcha"),
    ("recaptcha", "captcha", "recaptcha/api.js"),
    ("hcaptcha", "captcha", "hcaptcha.com/1/api.js"),
)

# Response header tell-tales -> (vendor, kind, required-substring-or-empty).
_BLOCK_HEADER_HINTS: tuple[tuple[str, str, str, str], ...] = (
    ("aws_waf", "interstitial", "x-amzn-waf-action", "challenge"),
    ("aws_waf", "captcha", "x-amzn-waf-action", "captcha"),
    ("cloudflare", "interstitial", "cf-mitigated", "challenge"),
    ("datadome", "interstitial", "x-dd-b", ""),
    ("datadome", "interstitial", "x-datadome-cid", ""),
    ("kasada", "js_challenge", "x-kpsdk-ct", ""),
)

# Only unambiguous active-challenge cookies (see module docstring).
_CHALLENGE_COOKIE_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("cloudflare", "js_challenge", "cf_chl_"),
)

# Ordered strongest-first so we can pick the most severe kind seen.
_KIND_SEVERITY: dict[str, int] = {
    "captcha": 5, "turnstile": 4, "js_challenge": 3,
    "interstitial": 2, "ratelimit": 1, "empty": 1, "none": 0,
}


def _lower_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {k.lower(): (v or "") for k, v in (headers or {}).items()}


def _cookies_from(headers: dict[str, str],
                  cookies: Mapping[str, str] | None) -> set[str]:
    names: set[str] = set()
    if cookies:
        names.update(cookies.keys())
    raw = headers.get("set-cookie")
    if raw:
        try:
            jar = SimpleCookie()
            jar.load(raw)
            names.update(jar.keys())
        except Exception:  # noqa: BLE001
            pass
    return names


def _looks_like_shell(status_code: int, headers: dict[str, str],
                      body: str) -> bool:
    """A tiny HTML page that is mostly script and no prose: a render shell."""
    if status_code != 200:
        return False
    ctype = headers.get("content-type", "")
    if "html" not in ctype and body[:200].lower().find("<html") == -1:
        return False
    if len(body) >= 1500:
        return False
    low = body.lower()
    if "<script" not in low:
        return False
    return low.count("<p") < 3


def classify_challenge(status_code: int,
                       headers: Mapping[str, str] | None,
                       body: str | None,
                       cookies: Mapping[str, str] | None = None) -> Verdict:
    """Classify a response as real content or a challenge, structured.

    Header/cookie signals are cheap and checked first, then a bounded body
    scan (first 16 KB; challenge pages are always small). Bare 401/403 with no
    vendor marker still counts as a block (a browser tier may clear it); 429 is
    a rate-limit (back off, do not escalate a tier).
    """
    headers_l = _lower_headers(headers)
    evidence: list[str] = []
    vendor: str | None = None
    kind: ChallengeKind = "none"

    def consider(v: str | None, k: str, marker: str) -> None:
        nonlocal vendor, kind
        evidence.append(marker)
        if v and vendor is None:
            vendor = v
        if _KIND_SEVERITY.get(k, 0) > _KIND_SEVERITY.get(kind, 0):
            kind = k  # type: ignore[assignment]

    # 1. Headers.
    for v, k, header, needle in _BLOCK_HEADER_HINTS:
        hv = headers_l.get(header)
        if hv is None:
            continue
        if needle == "" or needle in hv.lower():
            consider(v, k, f"header:{header}")

    # 2. Active-challenge cookies (conservative).
    cookie_names = _cookies_from(headers_l, cookies)
    for v, k, prefix in _CHALLENGE_COOKIE_PREFIXES:
        if any(name.startswith(prefix) for name in cookie_names):
            consider(v, k, f"cookie:{prefix}*")

    # 3. AWS WAF serves its JS challenge with status 202.
    if status_code == 202:
        consider("aws_waf", "js_challenge", "status:202")

    # 4. Body needles + challenge-widget scripts.
    if body:
        head = body[:16384].lower()
        for v, k, needle in _BLOCK_BODY_NEEDLES:
            if needle in head:
                consider(v, k, f"body:{needle[:24]}")
        for v, k, needle in _CHALLENGE_SCRIPT_MARKERS:
            if needle in head:
                consider(v, k, f"script:{needle[:24]}")

    marker_block = bool(evidence)

    # 5. Status-code layer (only decides escalation when no vendor marker).
    if not marker_block:
        if status_code in (401, 403):
            kind = "interstitial"
            evidence.append(f"status:{status_code}")
        elif status_code == 429:
            kind = "ratelimit"
            evidence.append("status:429")
        elif _looks_like_shell(status_code, headers_l, body or ""):
            kind = "js_challenge"
            evidence.append("heuristic:shell")

    blocked = bool(evidence) and kind != "none"
    escalate = kind in ("interstitial", "js_challenge", "turnstile", "captcha")
    if not blocked:
        confidence = 0.0
    elif marker_block:
        confidence = min(1.0, 0.6 + 0.15 * (len(evidence) - 1))
    else:
        confidence = 0.5 if kind != "js_challenge" else 0.4

    return Verdict(blocked=blocked, vendor=vendor, kind=kind,
                   confidence=round(confidence, 3), evidence=evidence,
                   escalate=escalate)


def detect_block(status_code: int, headers: Mapping[str, str],
                 body: str) -> str | None:
    """Back-compat shim: return the blocking vendor name, or None.

    Preserves the original narrow semantics (vendor markers only; a bare
    403/429 with no vendor fingerprint returns None).
    """
    return classify_challenge(status_code, headers, body).vendor

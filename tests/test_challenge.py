"""Tests for the WAF / challenge classifier."""
from __future__ import annotations

import pytest

from kewpie.challenge import classify_challenge, detect_block

_REAL_HTML = ("<html><body>" + "<p>real article content here</p>" * 10
              + "</body></html>")


@pytest.mark.parametrize("status,headers,body,exp_blocked,exp_vendor,exp_kind", [
    (200, {"content-type": "text/html"}, _REAL_HTML, False, None, "none"),
    (403, {"cf-mitigated": "challenge"}, "<title>Just a moment...</title>",
     True, "cloudflare", "interstitial"),
    (202, {}, "AwsWafIntegration challenge", True, "aws_waf", "js_challenge"),
    (200, {"content-type": "text/html"},
     'x <script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>',
     True, "cloudflare", "turnstile"),
    (200, {"content-type": "text/html"},
     'complete <script src="https://www.google.com/recaptcha/api.js"></script>',
     True, "recaptcha", "captcha"),
    (429, {}, "", True, None, "ratelimit"),
    (403, {}, "forbidden", True, None, "interstitial"),
    (200, {"x-dd-b": "1", "content-type": "text/html"}, _REAL_HTML,
     True, "datadome", "interstitial"),
])
def test_classify(status, headers, body, exp_blocked, exp_vendor, exp_kind):
    v = classify_challenge(status, headers, body)
    assert v.blocked is exp_blocked
    assert v.vendor == exp_vendor
    assert v.kind == exp_kind


def test_ratelimit_does_not_escalate():
    v = classify_challenge(429, {}, "")
    assert v.blocked is True
    assert v.escalate is False


def test_interstitial_escalates():
    v = classify_challenge(403, {"cf-mitigated": "challenge"}, "just a moment")
    assert v.escalate is True


def test_benign_cloudflare_cookie_is_not_a_block():
    # __cf_bm / cf_clearance are set on normal traffic -> must not flag a block.
    v = classify_challenge(
        200, {"set-cookie": "__cf_bm=abc; cf_clearance=xyz", "content-type": "text/html"},
        _REAL_HTML)
    assert v.blocked is False


def test_active_challenge_cookie_is_a_block():
    v = classify_challenge(
        403, {"set-cookie": "cf_chl_2=abc"}, "checking")
    assert v.blocked is True
    assert v.vendor == "cloudflare"


def test_tiny_shell_heuristic():
    v = classify_challenge(200, {"content-type": "text/html"},
                           "<html><script>render()</script></html>")
    assert v.kind == "js_challenge"
    assert v.escalate is True


def test_detect_block_shim_parity():
    # Narrow semantics: vendor markers only; a bare 403 returns None.
    assert detect_block(403, {}, "forbidden") is None
    assert detect_block(202, {}, "x") == "aws_waf"
    assert detect_block(200, {}, "ok") is None
    assert detect_block(403, {"cf-mitigated": "challenge"}, "") == "cloudflare"

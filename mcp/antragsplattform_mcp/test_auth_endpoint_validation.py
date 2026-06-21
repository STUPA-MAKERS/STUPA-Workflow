"""Tests for OAuth discovery-endpoint re-validation (AUD-023).

Discovery yields ``authorization_endpoint``/``token_endpoint`` that are used for the
browser redirect and the code/refresh-token POST. They MUST be re-validated to be
https (or loopback) AND same-origin as ``base_url`` so a tampered discovery body cannot
redirect credentials to a cleartext/cross-origin endpoint.
"""

from __future__ import annotations

import pytest

from antragsplattform_mcp.auth import AuthError, _require_secure_endpoint


BASE = "https://antrag.uni.de"


def test_same_origin_https_endpoint_accepted() -> None:
    _require_secure_endpoint("token_endpoint", f"{BASE}/oauth/token", BASE)


def test_same_origin_with_explicit_port_accepted() -> None:
    base = "https://antrag.uni.de:8443"
    _require_secure_endpoint("token_endpoint", f"{base}/oauth/token", base)


def test_loopback_http_same_origin_accepted() -> None:
    base = "http://127.0.0.1:8000"
    _require_secure_endpoint("authorization_endpoint", f"{base}/authorize", base)


def test_cleartext_attacker_endpoint_rejected() -> None:
    with pytest.raises(AuthError, match="requires https"):
        _require_secure_endpoint(
            "token_endpoint", "http://attacker.example/token", BASE
        )


def test_cross_origin_https_endpoint_rejected() -> None:
    with pytest.raises(AuthError, match="not same-origin"):
        _require_secure_endpoint(
            "token_endpoint", "https://attacker.example/token", BASE
        )


def test_cross_port_endpoint_rejected() -> None:
    with pytest.raises(AuthError, match="not same-origin"):
        _require_secure_endpoint(
            "token_endpoint", "https://antrag.uni.de:9999/token", BASE
        )


def test_subdomain_endpoint_rejected() -> None:
    # A different host (even a subdomain) is cross-origin and must be refused.
    with pytest.raises(AuthError, match="not same-origin"):
        _require_secure_endpoint(
            "authorization_endpoint", "https://evil.antrag.uni.de/authorize", BASE
        )

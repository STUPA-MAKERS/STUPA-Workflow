"""Tests for the API-path hardening in :mod:`antragsplattform_mcp.client`.

Covers AUD-022: caller-supplied ids interpolated into request paths must not be
able to perform path traversal (``../admin/audit``) or smuggle a query string
(``x?y=1``), while legitimate routes / UUID ids pass through untouched.
"""

from __future__ import annotations

import pytest

from .client import ApiError, _safe_path


def test_legitimate_paths_unchanged() -> None:
    for path in (
        "/applications",
        "/applications/3f9c1e2a-1b2c-4d5e-8f90-0a1b2c3d4e5f/votes",
        "/admin/application-types/abc-123/form-versions/latest",
        "/budgets/9e/expenses",
    ):
        assert _safe_path(path) == path


def test_traversal_segment_rejected() -> None:
    with pytest.raises(ApiError) as exc:
        _safe_path("/votes/../admin/audit")
    assert exc.value.status == 400


def test_trailing_traversal_rejected() -> None:
    with pytest.raises(ApiError):
        _safe_path("/votes/..")


def test_query_string_smuggling_rejected() -> None:
    with pytest.raises(ApiError) as exc:
        _safe_path("/votes/x?y=1")
    assert exc.value.status == 400


def test_fragment_and_backslash_rejected() -> None:
    with pytest.raises(ApiError):
        _safe_path("/votes/x#frag")
    with pytest.raises(ApiError):
        _safe_path("/votes/a\\b")


def test_special_chars_in_id_percent_encoded() -> None:
    assert _safe_path("/votes/a b") == "/votes/a%20b"
    assert _safe_path("/votes/a%2e%2e") == "/votes/a%252e%252e"


def test_relative_path_rejected() -> None:
    with pytest.raises(ApiError) as exc:
        _safe_path("votes/123")
    assert exc.value.status == 400

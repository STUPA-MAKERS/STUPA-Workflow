"""Restabdeckung files (T-13): Modell/Metadata + Attachment-Rate-Limit-Schlüssel."""

from __future__ import annotations

import uuid

import pytest

from app.db import Base
from app.modules.auth.principal import Applicant, Principal
from app.modules.files.models import MAX_ATTACHMENT_BYTES, Attachment
from app.settings import load_settings
from app.shared.antiabuse import rate_limit_attachments
from app.shared.errors import RateLimitedError
from app.shared.ratelimit import RateLimitResult

SETTINGS = load_settings()


# --------------------------------------------------------------------------- model
def test_attachment_table_registered() -> None:
    assert "attachment" in Base.metadata.tables
    table = Attachment.__table__
    assert {"id", "application_id", "filename", "mime", "size", "storage_key",
            "scanned", "scan_result", "is_comparison_offer"} <= set(table.columns.keys())


def test_attachment_size_check_constraint() -> None:
    checks = [
        c for c in Attachment.__table__.constraints  # type: ignore[attr-defined]
        if c.__class__.__name__ == "CheckConstraint"
    ]
    assert any(str(MAX_ATTACHMENT_BYTES) in str(c.sqltext) for c in checks)


def test_attachment_fk_cascade() -> None:
    fk = next(iter(Attachment.__table__.foreign_keys))
    assert fk.ondelete == "CASCADE"
    assert fk.column.table.name == "application"


# --------------------------------------------------------------------------- ratelimit
class _NullLimiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        self.keys.append(key)
        return RateLimitResult(allowed=True, retry_after=0)


class _DenyLimiter:
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        return RateLimitResult(allowed=False, retry_after=42)


class _FakeRequest:
    class _Client:
        host = "203.0.113.9"

    client = _Client()


def _principal() -> Principal:
    return Principal(sub="alice", permissions={"application.manage"})


def _applicant() -> Applicant:
    return Applicant(application_id=str(uuid.uuid4()), scope="edit")


async def test_ratelimit_key_principal() -> None:
    limiter = _NullLimiter()
    await rate_limit_attachments(
        _FakeRequest(), SETTINGS, limiter, _principal(), None  # type: ignore[arg-type]
    )
    assert limiter.keys == ["attachments:principal:alice"]


async def test_ratelimit_key_applicant() -> None:
    limiter = _NullLimiter()
    applicant = _applicant()
    await rate_limit_attachments(
        _FakeRequest(), SETTINGS, limiter, None, applicant  # type: ignore[arg-type]
    )
    assert limiter.keys == [f"attachments:applicant:{applicant.application_id}"]


async def test_ratelimit_key_ip_fallback() -> None:
    limiter = _NullLimiter()
    await rate_limit_attachments(
        _FakeRequest(), SETTINGS, limiter, None, None  # type: ignore[arg-type]
    )
    assert limiter.keys == ["attachments:ip:203.0.113.9"]


async def test_ratelimit_denied_raises_429() -> None:
    with pytest.raises(RateLimitedError):
        await rate_limit_attachments(
            _FakeRequest(), SETTINGS, _DenyLimiter(), _principal(), None  # type: ignore[arg-type]
        )

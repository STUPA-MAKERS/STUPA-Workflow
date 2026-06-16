"""TDD: Session-/Token-Handling (security.md §1/§2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from freezegun import freeze_time

from app.modules.auth import sessions
from app.modules.auth.models import AuthSession
from tests._support.auth_fakes import fake_session, result

SECRET = "session-signing-secret"
MAX_AGE = 3600


# --------------------------------------------------------------------------- #
# Applicant-Token
# --------------------------------------------------------------------------- #
def test_applicant_token_roundtrip() -> None:
    token = sessions.issue_applicant_token(SECRET, "app-1", "edit")
    data = sessions.load_applicant_token(SECRET, token, MAX_AGE)
    assert data == {"aid": "app-1", "scope": "edit"}


def test_applicant_token_bad_signature_returns_none() -> None:
    token = sessions.issue_applicant_token(SECRET, "app-1", "edit")
    assert sessions.load_applicant_token("wrong-secret", token, MAX_AGE) is None


def test_applicant_token_tampered_returns_none() -> None:
    assert sessions.load_applicant_token(SECRET, "not-a-token", MAX_AGE) is None


def test_applicant_token_expired_returns_none() -> None:
    with freeze_time("2026-01-01 00:00:00"):
        token = sessions.issue_applicant_token(SECRET, "app-1", "edit")
    with freeze_time("2026-01-01 02:00:00"):
        assert sessions.load_applicant_token(SECRET, token, MAX_AGE) is None


def test_applicant_token_wrong_shape_returns_none() -> None:
    # Gültig signiert, aber kein dict mit aid/scope.
    bad = sessions._serializer(SECRET, sessions._APPLICANT_SALT).dumps(["not", "a", "dict"])
    assert sessions.load_applicant_token(SECRET, bad, MAX_AGE) is None


# --------------------------------------------------------------------------- #
# OIDC-Transaktions-Cookie
# --------------------------------------------------------------------------- #
def test_oidc_tx_roundtrip() -> None:
    value = sessions.issue_oidc_tx(SECRET, "st", "vf", "nc")
    assert sessions.load_oidc_tx(SECRET, value, MAX_AGE) == {
        "state": "st",
        "verifier": "vf",
        "nonce": "nc",
    }


def test_oidc_tx_bad_signature_returns_none() -> None:
    value = sessions.issue_oidc_tx(SECRET, "st", "vf", "nc")
    assert sessions.load_oidc_tx("other", value, MAX_AGE) is None


def test_oidc_tx_wrong_shape_returns_none() -> None:
    bad = sessions._serializer(SECRET, sessions._OIDC_TX_SALT).dumps({"state": "x"})
    assert sessions.load_oidc_tx(SECRET, bad, MAX_AGE) is None


# --------------------------------------------------------------------------- #
# Principal-Session (serverseitig, DB via FakeSession)
# --------------------------------------------------------------------------- #
async def test_create_principal_session_adds_row_and_signs_sid() -> None:
    db = fake_session()
    exp = datetime.now(UTC) + timedelta(hours=12)
    cookie = await sessions.create_principal_session(
        db, secret=SECRET, principal_id="pid", expires_at=exp,
        refresh_token="rt", id_token="idt",
    )
    assert len(db.added) == 1
    assert isinstance(db.added[0], AuthSession)
    assert db.flushed == 1
    # Cookie ist signiert; rohe sid steckt nicht im Klartext.
    assert db.added[0].sid not in cookie


async def test_load_principal_session_valid() -> None:
    now = datetime.now(UTC)
    row = AuthSession(sid="s1", principal_id="pid", expires_at=now + timedelta(hours=1))
    db = fake_session(result(row))
    cookie = sessions._sign_sid(SECRET, "s1")
    loaded = await sessions.load_principal_session(
        db, secret=SECRET, cookie_value=cookie, now=now, max_age=MAX_AGE
    )
    assert loaded is row


async def test_load_principal_session_bad_cookie() -> None:
    db = fake_session()
    loaded = await sessions.load_principal_session(
        db, secret=SECRET, cookie_value="garbage", now=datetime.now(UTC), max_age=MAX_AGE
    )
    assert loaded is None


async def test_load_principal_session_unknown_sid() -> None:
    db = fake_session(result())  # keine Zeile
    cookie = sessions._sign_sid(SECRET, "s1")
    loaded = await sessions.load_principal_session(
        db, secret=SECRET, cookie_value=cookie, now=datetime.now(UTC), max_age=MAX_AGE
    )
    assert loaded is None


async def test_load_principal_session_expired() -> None:
    now = datetime.now(UTC)
    row = AuthSession(sid="s1", principal_id="pid", expires_at=now - timedelta(seconds=1))
    db = fake_session(result(row))
    cookie = sessions._sign_sid(SECRET, "s1")
    loaded = await sessions.load_principal_session(
        db, secret=SECRET, cookie_value=cookie, now=now, max_age=MAX_AGE
    )
    assert loaded is None


async def test_delete_principal_session_ok() -> None:
    row = AuthSession(sid="s1", principal_id="pid", expires_at=datetime.now(UTC))
    db = fake_session(result(row))
    cookie = sessions._sign_sid(SECRET, "s1")
    deleted = await sessions.delete_principal_session(
        db, secret=SECRET, cookie_value=cookie, max_age=MAX_AGE
    )
    assert deleted is row
    assert db.deleted == [row]
    assert db.flushed == 1


async def test_delete_principal_session_bad_cookie() -> None:
    db = fake_session()
    assert (
        await sessions.delete_principal_session(
            db, secret=SECRET, cookie_value="garbage", max_age=MAX_AGE
        )
        is None
    )


async def test_delete_principal_session_unknown_sid() -> None:
    db = fake_session(result())
    cookie = sessions._sign_sid(SECRET, "s1")
    assert (
        await sessions.delete_principal_session(
            db, secret=SECRET, cookie_value=cookie, max_age=MAX_AGE
        )
        is None
    )

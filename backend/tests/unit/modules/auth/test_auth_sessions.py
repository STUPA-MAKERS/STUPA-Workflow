"""TDD: Session-/Token-Handling (security.md §1/§2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from freezegun import freeze_time

from app.modules.auth import sessions
from app.modules.auth.models import ApplicantSession, AuthSession
from tests._support.auth_fakes import fake_session, result

SECRET = "session-signing-secret"
MAX_AGE = 3600


def _applicant_row(
    *, sid: str = "as1", scope: str = "edit", expired: bool = False, revoked: bool = False
) -> ApplicantSession:
    now = datetime.now(UTC)
    row = ApplicantSession(
        sid=sid,
        application_id="app-1",
        scope=scope,
        expires_at=now - timedelta(seconds=1) if expired else now + timedelta(hours=1),
    )
    if revoked:
        row.revoked_at = now
    return row


# --------------------------------------------------------------------------- #
# Applicant-Session (serverseitig, DB via FakeSession) — security.md §1:
# stateless-Token durch widerrufbare, NICHT allein-aus-Secret-fälschbare Session ersetzt.
# --------------------------------------------------------------------------- #
async def test_create_applicant_session_adds_row_and_signs_sid() -> None:
    db = fake_session()
    exp = datetime.now(UTC) + timedelta(hours=12)
    cookie = await sessions.create_applicant_session(
        db, secret=SECRET, application_id="app-1", scope="edit", expires_at=exp
    )
    assert len(db.added) == 1
    assert isinstance(db.added[0], ApplicantSession)
    assert db.added[0].scope == "edit"
    assert db.flushed == 1
    # Cookie ist signiert; die rohe sid steckt nicht im Klartext.
    assert db.added[0].sid not in cookie
    # Die signierte sid ist mit demselben Secret wieder auslesbar.
    assert sessions._unsign_applicant_sid(SECRET, cookie, MAX_AGE) == db.added[0].sid


async def test_load_applicant_session_valid() -> None:
    now = datetime.now(UTC)
    row = _applicant_row()
    db = fake_session(result(row))
    cookie = sessions._sign_applicant_sid(SECRET, row.sid)
    loaded = await sessions.load_applicant_session(
        db, secret=SECRET, cookie_value=cookie, now=now, max_age=MAX_AGE
    )
    assert loaded is row


async def test_load_applicant_session_bad_signature() -> None:
    # Falsches Secret (≈ kein Secret): Signatur scheitert → None, DB nie befragt.
    db = fake_session()
    row = _applicant_row()
    cookie = sessions._sign_applicant_sid(SECRET, row.sid)
    loaded = await sessions.load_applicant_session(
        db, secret="wrong-secret", cookie_value=cookie, now=datetime.now(UTC),
        max_age=MAX_AGE,
    )
    assert loaded is None


async def test_load_applicant_session_tampered() -> None:
    db = fake_session()
    loaded = await sessions.load_applicant_session(
        db, secret=SECRET, cookie_value="not-a-token", now=datetime.now(UTC),
        max_age=MAX_AGE,
    )
    assert loaded is None


async def test_load_applicant_session_forged_secret_no_row() -> None:
    # KERN-REGRESSION: korrekt signierte sid, aber KEINE Zeile → None. Wer nur das
    # Secret kennt, kann keine Zeile erfinden (security.md §1, Issue ISSUE_TOKEN).
    db = fake_session(result())  # leeres Ergebnis
    cookie = sessions._sign_applicant_sid(SECRET, "forged-sid")
    loaded = await sessions.load_applicant_session(
        db, secret=SECRET, cookie_value=cookie, now=datetime.now(UTC), max_age=MAX_AGE
    )
    assert loaded is None


async def test_load_applicant_session_revoked() -> None:
    now = datetime.now(UTC)
    row = _applicant_row(revoked=True)
    db = fake_session(result(row))
    cookie = sessions._sign_applicant_sid(SECRET, row.sid)
    loaded = await sessions.load_applicant_session(
        db, secret=SECRET, cookie_value=cookie, now=now, max_age=MAX_AGE
    )
    assert loaded is None


async def test_load_applicant_session_expired() -> None:
    now = datetime.now(UTC)
    row = _applicant_row(expired=True)
    db = fake_session(result(row))
    cookie = sessions._sign_applicant_sid(SECRET, row.sid)
    loaded = await sessions.load_applicant_session(
        db, secret=SECRET, cookie_value=cookie, now=now, max_age=MAX_AGE
    )
    assert loaded is None


async def test_load_applicant_session_signature_expired() -> None:
    with freeze_time("2026-01-01 00:00:00"):
        cookie = sessions._sign_applicant_sid(SECRET, "as1")
    with freeze_time("2026-01-01 02:00:00"):
        loaded = await sessions.load_applicant_session(
            fake_session(), secret=SECRET, cookie_value=cookie,
            now=datetime.now(UTC), max_age=MAX_AGE,
        )
    assert loaded is None


async def test_delete_applicant_session_ok() -> None:
    row = _applicant_row()
    db = fake_session(result(row))
    cookie = sessions._sign_applicant_sid(SECRET, row.sid)
    deleted = await sessions.delete_applicant_session(
        db, secret=SECRET, cookie_value=cookie, max_age=MAX_AGE
    )
    assert deleted is row
    assert db.deleted == [row]
    assert db.flushed == 1


async def test_delete_applicant_session_bad_cookie() -> None:
    db = fake_session()
    assert (
        await sessions.delete_applicant_session(
            db, secret=SECRET, cookie_value="garbage", max_age=MAX_AGE
        )
        is None
    )


async def test_delete_applicant_session_unknown_sid() -> None:
    db = fake_session(result())
    cookie = sessions._sign_applicant_sid(SECRET, "as1")
    assert (
        await sessions.delete_applicant_session(
            db, secret=SECRET, cookie_value=cookie, max_age=MAX_AGE
        )
        is None
    )


async def test_load_applicant_session_non_str_sid() -> None:
    # Gültig signiert, aber kein String (Tamper/Programmierfehler) → None vor DB-Lookup.
    bad = sessions._serializer(SECRET, sessions._APPLICANT_SALT).dumps(["not", "a", "str"])
    loaded = await sessions.load_applicant_session(
        fake_session(), secret=SECRET, cookie_value=bad, now=datetime.now(UTC),
        max_age=MAX_AGE,
    )
    assert loaded is None


async def test_revoke_applicant_sessions_runs() -> None:
    # Kill-Switch (Anonymisierung): setzt revoked_at per UPDATE; läuft fehlerfrei.
    db = fake_session()
    await sessions.revoke_applicant_sessions(db, "app-1", now=datetime.now(UTC))


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

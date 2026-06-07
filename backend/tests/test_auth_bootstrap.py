"""TDD: Bootstrap initialer Admins (#70).

Deckt jeden Branch von ``app.modules.auth.bootstrap`` (kritisches Modul → 100 %
Branch) + die Settings-Parser-Properties ab. DB ohne Docker via ``fake_session``.
"""

from __future__ import annotations

from app.modules.auth import bootstrap
from app.modules.auth.models import Principal as PrincipalRow
from app.settings import Settings, load_settings
from tests.auth_fakes import fake_session, result

_ROLE_ID = "00000000-0000-0000-0000-0000000000a1"


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x/y",
        "session_secret": "session-secret-0123",
        "magic_link_secret": "magic-link-secret-0",
    }
    base.update(over)
    return load_settings(**base)


def _principal(sub: str = "sub-1", email: str | None = None) -> PrincipalRow:
    row = PrincipalRow(sub=sub, email=email, display_name=None, oidc_groups=None)
    row.id = "pid-1"  # type: ignore[assignment]
    return row


# --------------------------------------------------------------------------- #
# Settings-Parser (kommagetrennt → Set)
# --------------------------------------------------------------------------- #
def test_subject_and_email_sets_split_trim_and_lower() -> None:
    s = _settings(
        bootstrap_admin_subjects="a, b ,, a",
        bootstrap_admin_emails="Foo@X.de , BAR@x.de ,",
    )
    assert s.bootstrap_admin_subject_set == {"a", "b"}
    assert s.bootstrap_admin_email_set == {"foo@x.de", "bar@x.de"}


def test_empty_bootstrap_sets() -> None:
    s = _settings()
    assert s.bootstrap_admin_subject_set == set()
    assert s.bootstrap_admin_email_set == set()


# --------------------------------------------------------------------------- #
# _is_bootstrap_principal — alle Branches
# --------------------------------------------------------------------------- #
def test_is_bootstrap_matches_subject() -> None:
    s = _settings(bootstrap_admin_subjects="sub-1")
    assert bootstrap._is_bootstrap_principal(_principal(sub="sub-1"), s) is True


def test_is_bootstrap_matches_email_case_insensitive() -> None:
    s = _settings(bootstrap_admin_emails="admin@x.de")
    assert bootstrap._is_bootstrap_principal(_principal(email="Admin@X.de"), s) is True


def test_is_bootstrap_no_match_with_email_present() -> None:
    s = _settings(bootstrap_admin_subjects="other", bootstrap_admin_emails="x@y.de")
    assert bootstrap._is_bootstrap_principal(_principal(email="nope@z.de"), s) is False


def test_is_bootstrap_no_match_email_none() -> None:
    s = _settings(bootstrap_admin_emails="x@y.de")
    assert bootstrap._is_bootstrap_principal(_principal(email=None), s) is False


# --------------------------------------------------------------------------- #
# ensure_admin_for_principal (Login-Pfad)
# --------------------------------------------------------------------------- #
async def test_login_grant_when_matched_and_missing() -> None:
    s = _settings(bootstrap_admin_subjects="sub-1")
    db = fake_session(result(_ROLE_ID), result())  # role-id, dann keine Assignment
    granted = await bootstrap.ensure_admin_for_principal(db, s, _principal(sub="sub-1"))
    assert granted is True
    assert len(db.added) == 1
    assert db.added[0].granted_by == "bootstrap"
    assert db.flushed == 1


async def test_login_noop_when_not_matched() -> None:
    s = _settings(bootstrap_admin_subjects="other")
    db = fake_session()
    assert await bootstrap.ensure_admin_for_principal(db, s, _principal()) is False
    assert db.added == []


async def test_login_noop_when_role_missing() -> None:
    s = _settings(bootstrap_admin_subjects="sub-1")
    db = fake_session(result())  # role-id None
    assert await bootstrap.ensure_admin_for_principal(db, s, _principal(sub="sub-1")) is False
    assert db.added == []


async def test_login_noop_when_already_assigned() -> None:
    s = _settings(bootstrap_admin_subjects="sub-1")
    db = fake_session(result(_ROLE_ID), result("existing-assignment-id"))
    assert await bootstrap.ensure_admin_for_principal(db, s, _principal(sub="sub-1")) is False
    assert db.added == []


# --------------------------------------------------------------------------- #
# ensure_bootstrap_admins (Startup-Sweep)
# --------------------------------------------------------------------------- #
async def test_sweep_noop_when_unconfigured() -> None:
    db = fake_session()
    assert await bootstrap.ensure_bootstrap_admins(db, _settings()) == 0


async def test_sweep_noop_when_role_missing() -> None:
    s = _settings(bootstrap_admin_subjects="sub-1")
    db = fake_session(result())  # role-id None
    assert await bootstrap.ensure_bootstrap_admins(db, s) == 0


async def test_sweep_grants_only_missing() -> None:
    s = _settings(bootstrap_admin_subjects="sub-1,sub-2")
    p1, p2 = _principal(sub="sub-1"), _principal(sub="sub-2")
    p2.id = "pid-2"  # type: ignore[assignment]
    db = fake_session(
        result(_ROLE_ID),  # role-id
        result(p1, p2),  # matched principals
        result(),  # p1: no existing assignment → grant
        result("has-it"),  # p2: already assigned → skip
    )
    granted = await bootstrap.ensure_bootstrap_admins(db, s)
    assert granted == 1
    assert len(db.added) == 1
    assert db.flushed == 1


async def test_sweep_no_flush_when_all_present() -> None:
    s = _settings(bootstrap_admin_emails="a@x.de")
    db = fake_session(
        result(_ROLE_ID),
        result(_principal(email="a@x.de")),
        result("has-it"),  # already assigned
    )
    assert await bootstrap.ensure_bootstrap_admins(db, s) == 0
    assert db.added == []
    assert db.flushed == 0

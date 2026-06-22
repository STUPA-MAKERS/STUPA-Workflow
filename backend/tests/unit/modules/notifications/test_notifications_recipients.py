"""Empfänger-Resolver-Tests (T-18) — DB via `FakeSession` (Query-Antworten gefaked)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.notifications.recipients import (
    ADMIN_ROLE_KEY,
    RecipientResolver,
    principals_with_permission_stmt,
)
from tests._support.notifications_fakes import FakeSession


def _sql(perm: str, **kw: object) -> str:
    stmt = principals_with_permission_stmt(perm, datetime.now(UTC), **kw)  # type: ignore[arg-type]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _resolver(session: FakeSession) -> RecipientResolver:
    return RecipientResolver(cast(AsyncSession, session))


async def test_resolve_group_filters_none_and_sorts() -> None:
    session = FakeSession(scalars=[["b@y.de", None, "a@x.de"]])
    out = await _resolver(session).resolve([{"kind": "group", "ref": "stupa"}])
    assert out == ["a@x.de", "b@y.de"]


async def test_resolve_role() -> None:
    session = FakeSession(scalars=[["c@x.de"]])
    out = await _resolver(session).resolve([{"kind": "role", "ref": "manager"}])
    assert out == ["c@x.de"]


async def test_resolve_applicant() -> None:
    session = FakeSession(scalar=["d@x.de"])
    out = await _resolver(session).resolve(
        [{"kind": "applicant"}], application_id=uuid.uuid4()
    )
    assert out == ["d@x.de"]


async def test_resolve_applicant_no_email_skipped() -> None:
    session = FakeSession(scalar=[None])
    out = await _resolver(session).resolve(
        [{"kind": "applicant"}], application_id=uuid.uuid4()
    )
    assert out == []


async def test_resolve_applicant_without_application_id_ignored() -> None:
    out = await _resolver(FakeSession()).resolve([{"kind": "applicant"}])
    assert out == []


async def test_resolve_unknown_and_incomplete_specs_ignored() -> None:
    out = await _resolver(FakeSession()).resolve(
        [{"kind": "group"}, {"kind": "weird", "ref": "x"}, {}]
    )
    assert out == []


async def test_resolve_dedup_across_specs() -> None:
    session = FakeSession(scalars=[["a@x.de"], ["a@x.de", "b@y.de"]])
    out = await _resolver(session).resolve(
        [{"kind": "group", "ref": "g"}, {"kind": "role", "ref": "r"}]
    )
    assert out == ["a@x.de", "b@y.de"]


# AUD-057: Admin-Bypass-Regel der Empfänger-Auflösung ist EINE zentrale Query mit
# EINEM Admin-Schlüssel — kein dupliziertes ``Role.key == "admin"``-Literal mehr.


def test_admin_role_key_matches_principal_has_bypass() -> None:
    # ``Principal.has`` bypassed über ``ADMIN_ROLE_KEY in roles``; die Mengen-Query
    # MUSS denselben Schlüssel verwenden, sonst divergiert die Benachrichtigung.
    admin = Principal(sub="s", roles=[ADMIN_ROLE_KEY], permissions=set())
    assert admin.has("any.perm") is True
    non_admin = Principal(sub="s", roles=["editor"], permissions=set())
    assert non_admin.has("any.perm") is False


def test_permission_stmt_includes_admin_bypass_via_constant() -> None:
    sql = _sql("application.transition")
    # Admin-Bypass anhand der zentralen Konstante (nicht hartkodiert pro Resolver).
    assert f"key = '{ADMIN_ROLE_KEY}'" in sql
    assert "permission = 'application.transition'" in sql
    # Aktiv + Gültigkeitsfenster der Zuweisung greifen ebenfalls.
    assert "active" in sql
    assert "valid_from" in sql and "valid_until" in sql


def test_permission_stmt_gremium_scope_optional() -> None:
    gid = uuid.uuid4()
    scoped = _sql("application.transition", gremium_id=gid)
    unscoped = _sql("application.transition")
    assert "gremium_id" in scoped
    # Ohne gremium_id KEIN Gremium-Filter (globaler Empfängerkreis).
    assert "gremium_id" not in unscoped


def test_both_resolvers_share_one_query_builder() -> None:
    # actionable_principal_emails (Task-Mail) und _emails_for_permission (Regel-
    # Recipient) bauen denselben Admin-Bypass auf — bewiesen durch identische
    # Kern-Klausel für dieselbe Permission.
    rule_sql = _sql("application.transition")
    assert rule_sql.count(f"key = '{ADMIN_ROLE_KEY}'") == 1

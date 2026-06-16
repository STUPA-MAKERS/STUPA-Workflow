"""Empfänger-Resolver-Tests (T-18) — DB via `FakeSession` (Query-Antworten gefaked)."""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.recipients import RecipientResolver
from tests._support.notifications_fakes import FakeSession


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

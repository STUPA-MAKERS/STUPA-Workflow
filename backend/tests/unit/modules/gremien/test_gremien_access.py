"""Unit tests of the gate of the tab "Gremien": member, ``gremium.view_all``, admin, else 404."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.auth.principal import Principal
from app.modules.gremien import access
from app.shared.errors import NotFoundError
from tests._support.auth_fakes import fake_session, result

GID = uuid.uuid4()


def test_views_all_for_permission_and_admin() -> None:
    assert access.views_all(Principal(sub="a", permissions={"gremium.view_all"}))
    assert access.views_all(Principal(sub="a", roles=["admin"]))
    assert not access.views_all(Principal(sub="a"))


def test_views_all_respects_the_scope_cap() -> None:
    token = Principal(sub="a", roles=["admin"], scope_permissions=frozenset({"application.read"}))
    assert not access.views_all(token)


async def test_member_gremium_ids_reads_the_rows() -> None:
    db = fake_session(result(GID))
    assert await access.member_gremium_ids(db, Principal(sub="a")) == {GID}


async def test_can_view_short_cuts_for_view_all() -> None:
    # No query: the session has no result queued and would give an empty set.
    assert await access.can_view_gremium(fake_session(), Principal(sub="a", roles=["admin"]), GID)


async def test_can_view_as_member_and_not() -> None:
    assert await access.can_view_gremium(fake_session(result(GID)), Principal(sub="a"), GID)
    assert not await access.can_view_gremium(fake_session(result()), Principal(sub="a"), GID)


async def test_require_gremium_returns_the_row() -> None:
    row = SimpleNamespace(id=GID)
    db = fake_session(result(GID), gets=[row])
    assert await access.require_gremium(db, Principal(sub="a"), GID) is row


@pytest.mark.parametrize("member", [True, False])
async def test_require_gremium_404(member: bool) -> None:
    # Unknown gremium: 404 even for a member of another one. Hidden gremium: the same 404.
    db = (
        fake_session(result()) if member else fake_session(result(), gets=[SimpleNamespace(id=GID)])
    )
    with pytest.raises(NotFoundError) as err:
        await access.require_gremium(db, Principal(sub="a"), GID)
    assert err.value.code == "gremium_not_found"

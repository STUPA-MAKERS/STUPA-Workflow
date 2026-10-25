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
ROLE = SimpleNamespace(permissions=[])


def test_views_all_for_permission_and_admin() -> None:
    assert access.views_all(Principal(sub="a", permissions={"gremium.view_all"}))
    assert access.views_all(Principal(sub="a", roles=["admin"]))
    assert not access.views_all(Principal(sub="a"))


def test_views_all_respects_the_scope_cap() -> None:
    token = Principal(sub="a", roles=["admin"], scope_permissions=frozenset({"application.read"}))
    assert not access.views_all(token)


async def test_require_gremium_for_view_all_reads_no_membership() -> None:
    """Open the gremium by view_all alone, without a membership read."""
    row = SimpleNamespace(id=GID)
    db = fake_session(gets=[row])
    assert await access.require_gremium(db, Principal(sub="a", roles=["admin"]), GID) is row


async def test_require_gremium_for_a_member() -> None:
    row = SimpleNamespace(id=GID)
    db = fake_session(result((GID, ROLE)), gets=[row])
    assert await access.require_gremium(db, Principal(sub="a"), GID) is row


async def test_require_gremium_hides_a_member_gremium_from_a_capped_token() -> None:
    """Hide a member gremium from a capped token; no membership query runs."""
    token = Principal(sub="a", scope_permissions=frozenset({"budget.write"}))
    db = fake_session(gets=[SimpleNamespace(id=GID)])
    with pytest.raises(NotFoundError):
        await access.require_gremium(db, token, GID)


@pytest.mark.parametrize("exists", [True, False])
async def test_require_gremium_404(exists: bool) -> None:
    """Give the same 404 for an unknown gremium and a hidden gremium."""
    gets = [SimpleNamespace(id=GID)] if exists else [None]
    db = fake_session(result((uuid.uuid4(), ROLE)), gets=gets)
    with pytest.raises(NotFoundError) as err:
        await access.require_gremium(db, Principal(sub="a"), GID)
    assert err.value.code == "gremium_not_found"

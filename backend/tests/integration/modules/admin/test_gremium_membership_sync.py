"""Integration (real Postgres): the gremium memberships come from the OIDC groups only.

The tests run against the migrated schema. They prove these facts:

- the OIDC login writes the memberships from the group claim and the mappings, and a
  later login with other groups changes or removes them.
- a create, change or delete of a mapping syncs all principals at once.
- the RBAC resolver reads the synced membership as a `vote.cast` eligibility.
- the erasure of a principal removes its memberships.
- the EXCLUDE constraint still allows one row per (principal, gremium) only.
- a gremium role that a mapping uses cannot be deleted, and a duplicate group in one
  gremium gives 409.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.admin.schemas import GremiumGroupMappingCreate, GremiumGroupMappingUpdate
from app.modules.auth import service as auth_service
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oidc import OidcClaims
from app.modules.auth.rbac import resolve_principal, vote_group_key
from app.modules.privacy.service import PrincipalService
from app.settings import Settings, load_settings
from app.shared.errors import ConflictError

pytestmark = pytest.mark.integration

_ACTOR = "admin-sub"


@pytest.fixture
async def session(migrated: tuple[str, str]) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _gremium(session: AsyncSession) -> tuple[Gremium, GremiumRole, GremiumRole]:
    """Create a gremium with its forced roles. Return it, `member` and `vorstand`."""
    gremium = Gremium(name="StuPa", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    await GremiumRoleService(session).ensure_forced_roles(gremium.id)
    roles = {
        r.key: r
        for r in (
            await session.scalars(select(GremiumRole).where(GremiumRole.gremium_id == gremium.id))
        ).all()
    }
    await session.commit()
    return gremium, roles["member"], roles["vorstand"]


async def _principal(session: AsyncSession, groups: list[str] | None) -> PrincipalRow:
    row = PrincipalRow(sub=f"s-{uuid.uuid4()}", display_name="Mara", oidc_groups=groups)
    session.add(row)
    await session.commit()
    return row


async def _roles_of(session: AsyncSession, principal: PrincipalRow) -> dict[uuid.UUID, uuid.UUID]:
    rows = (
        await session.scalars(
            select(GremiumMembership).where(GremiumMembership.principal_id == principal.id)
        )
    ).all()
    return {m.gremium_id: m.gremium_role_id for m in rows}


def _mapping(group: str, role: GremiumRole) -> GremiumGroupMappingCreate:
    return GremiumGroupMappingCreate.model_validate(
        {"oidcGroup": group, "gremiumRoleId": str(role.id)}
    )


async def _login(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, sub: str, groups: list[str]
) -> PrincipalRow:
    """Run the OIDC callback with a stubbed IdP that sends ``groups``."""

    async def _exchange(_s: Settings, *, code: str, verifier: str) -> dict[str, str]:
        return {"id_token": "idt"}

    async def _verify(_s: Settings, *, id_token: str, nonce: str) -> OidcClaims:
        return OidcClaims(sub=sub, email=None, name="Mara", groups=groups, email_verified=False)

    monkeypatch.setattr(auth_service.oidc, "exchange_code", _exchange)
    monkeypatch.setattr(auth_service.oidc, "verify_id_token", _verify)
    settings = load_settings(
        database_url="postgresql+asyncpg://unused/x",
        session_secret="session-secret-0123456",
        magic_link_secret="magic-link-secret-0",
    )
    _cookie, row = await auth_service.oidc_callback(
        session, settings, code="c", verifier="v", nonce="n"
    )
    await session.commit()
    return row


async def test_login_writes_changes_and_removes_memberships(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    gremium, member, board = await _gremium(session)
    svc = GremiumRoleService(session)
    await svc.create_group_mapping(gremium.id, _mapping(f"{gremium.slug}-m", member), _ACTOR)
    await svc.create_group_mapping(gremium.id, _mapping(f"{gremium.slug}-b", board), _ACTOR)
    sub = f"s-{uuid.uuid4()}"

    row = await _login(session, monkeypatch, sub, [f"{gremium.slug}-m"])
    assert await _roles_of(session, row) == {gremium.id: member.id}
    resolved = await resolve_principal(session, row, datetime.now(UTC))
    assert vote_group_key(gremium.id) in resolved.groups

    # In both groups the role with more permissions wins.
    row = await _login(session, monkeypatch, sub, [f"{gremium.slug}-m", f"{gremium.slug}-b"])
    assert await _roles_of(session, row) == {gremium.id: board.id}

    row = await _login(session, monkeypatch, sub, ["unrelated"])
    assert await _roles_of(session, row) == {}


async def test_mapping_changes_sync_all_principals(session: AsyncSession) -> None:
    gremium, member, board = await _gremium(session)
    group = f"{gremium.slug}-all"
    alice = await _principal(session, [group])
    bob = await _principal(session, [group, "other"])
    outsider = await _principal(session, ["other"])
    svc = GremiumRoleService(session)

    created = await svc.create_group_mapping(gremium.id, _mapping(group, member), _ACTOR)
    assert await _roles_of(session, alice) == {gremium.id: member.id}
    assert await _roles_of(session, bob) == {gremium.id: member.id}
    assert await _roles_of(session, outsider) == {}
    assert [m.principal_id for m in await svc.list_memberships(gremium.id)].count(alice.id) == 1

    await svc.update_group_mapping(
        created.id,
        GremiumGroupMappingUpdate.model_validate({"gremiumRoleId": str(board.id)}),
        _ACTOR,
    )
    assert await _roles_of(session, alice) == {gremium.id: board.id}

    # The role is in use by the mapping, so nobody can delete it.
    custom = GremiumRole(gremium_id=gremium.id, key="custom", name_i18n={}, permissions=[])
    session.add(custom)
    await session.commit()
    await svc.update_group_mapping(
        created.id,
        GremiumGroupMappingUpdate.model_validate({"gremiumRoleId": str(custom.id)}),
        _ACTOR,
    )
    with pytest.raises(ConflictError, match="in use"):
        await svc.delete_role(custom.id, _ACTOR)

    await svc.delete_group_mapping(created.id, _ACTOR)
    assert await _roles_of(session, alice) == {}
    assert await _roles_of(session, bob) == {}
    await svc.delete_role(custom.id, _ACTOR)


async def test_duplicate_group_in_one_gremium_gives_409(session: AsyncSession) -> None:
    gremium, member, board = await _gremium(session)
    svc = GremiumRoleService(session)
    await svc.create_group_mapping(gremium.id, _mapping("dup", member), _ACTOR)
    with pytest.raises(ConflictError, match="already maps"):
        await svc.create_group_mapping(gremium.id, _mapping("dup", board), _ACTOR)
    # The same group may map into another gremium.
    other, other_member, _ = await _gremium(session)
    await svc.create_group_mapping(other.id, _mapping("dup", other_member), _ACTOR)


async def test_erasure_removes_memberships(session: AsyncSession) -> None:
    gremium, member, _ = await _gremium(session)
    row = await _principal(session, ["erase-me"])
    await GremiumRoleService(session).create_group_mapping(
        gremium.id, _mapping("erase-me", member), _ACTOR
    )
    assert await _roles_of(session, row) == {gremium.id: member.id}
    await PrincipalService(session).erase(row.id, actor=_ACTOR)
    assert await _roles_of(session, row) == {}


async def test_db_allows_one_membership_per_principal_and_gremium(
    session: AsyncSession,
) -> None:
    gremium, member, board = await _gremium(session)
    row = await _principal(session, None)
    session.add(
        GremiumMembership(principal_id=row.id, gremium_id=gremium.id, gremium_role_id=member.id)
    )
    await session.commit()
    session.add(
        GremiumMembership(principal_id=row.id, gremium_id=gremium.id, gremium_role_id=board.id)
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

"""Integration (real Postgres): the gremium memberships come from the OIDC groups only.

An OIDC group links in separate ways: to the membership in a gremium, and to a role in
a gremium. The tests run against the migrated schema. They prove these facts:

- the OIDC login writes the memberships from the group claim and the mappings. A later
  login with other groups changes or removes them.
- a member without a role mapping has the forced role `member`. A role mapping applies
  only to a member. It never makes a principal a member.
- a create, change or delete of a mapping syncs all principals at once.
- the RBAC resolver reads the synced membership as a `vote.cast` eligibility.
- the erasure of a principal removes its memberships.
- the EXCLUDE constraint still allows one row per (principal, gremium) only.
- a gremium role that a mapping uses cannot be deleted. A duplicate mapping gives 409.
- the global group mapping has no gremium scope any more.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.admin.oidc_mappings import OidcMappingService
from app.modules.admin.schemas import (
    GremiumMembershipMappingCreate,
    GremiumRoleMappingCreate,
    GremiumRoleMappingUpdate,
)
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


def _member_of(group: str, gremium: Gremium) -> GremiumMembershipMappingCreate:
    return GremiumMembershipMappingCreate.model_validate(
        {"oidcGroup": group, "gremiumId": str(gremium.id)}
    )


def _role_for(group: str, role: GremiumRole) -> GremiumRoleMappingCreate:
    return GremiumRoleMappingCreate.model_validate(
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
    svc = OidcMappingService(session)
    members, chairs = f"{gremium.slug}-m", f"{gremium.slug}-b"
    await svc.create_membership_mapping(_member_of(members, gremium), _ACTOR)
    await svc.create_role_mapping(_role_for(chairs, board), _ACTOR)
    sub = f"s-{uuid.uuid4()}"

    # The role group alone makes nobody a member.
    row = await _login(session, monkeypatch, sub, [chairs])
    assert await _roles_of(session, row) == {}

    # A member without a role mapping has the forced role `member`.
    row = await _login(session, monkeypatch, sub, [members])
    assert await _roles_of(session, row) == {gremium.id: member.id}
    resolved = await resolve_principal(session, row, datetime.now(UTC))
    assert vote_group_key(gremium.id) in resolved.groups

    # A member in the role group has that role.
    row = await _login(session, monkeypatch, sub, [members, chairs])
    assert await _roles_of(session, row) == {gremium.id: board.id}

    row = await _login(session, monkeypatch, sub, ["unrelated"])
    assert await _roles_of(session, row) == {}


async def test_mapping_changes_sync_all_principals(session: AsyncSession) -> None:
    gremium, member, board = await _gremium(session)
    members, chairs = f"{gremium.slug}-all", f"{gremium.slug}-chairs"
    alice = await _principal(session, [members, chairs])
    bob = await _principal(session, [members, "other"])
    outsider = await _principal(session, [chairs])
    svc = OidcMappingService(session)

    membership = await svc.create_membership_mapping(_member_of(members, gremium), _ACTOR)
    assert await _roles_of(session, alice) == {gremium.id: member.id}
    assert await _roles_of(session, bob) == {gremium.id: member.id}
    assert await _roles_of(session, outsider) == {}

    role_mapping = await svc.create_role_mapping(_role_for(chairs, board), _ACTOR)
    assert await _roles_of(session, alice) == {gremium.id: board.id}
    assert await _roles_of(session, bob) == {gremium.id: member.id}
    assert await _roles_of(session, outsider) == {}
    [listed] = [m for m in await svc.list_role_mappings() if m.id == role_mapping.id]
    assert listed.gremium_id == gremium.id

    # The role is in use by the mapping, so nobody can delete it.
    custom = GremiumRole(gremium_id=gremium.id, key="custom", name_i18n={}, permissions=[])
    session.add(custom)
    await session.commit()
    await svc.update_role_mapping(
        role_mapping.id,
        GremiumRoleMappingUpdate.model_validate({"gremiumRoleId": str(custom.id)}),
        _ACTOR,
    )
    with pytest.raises(ConflictError, match="in use"):
        await GremiumRoleService(session).delete_role(custom.id, _ACTOR)

    await svc.delete_role_mapping(role_mapping.id, _ACTOR)
    assert await _roles_of(session, alice) == {gremium.id: member.id}
    await GremiumRoleService(session).delete_role(custom.id, _ACTOR)

    await svc.delete_membership_mapping(membership.id, _ACTOR)
    assert await _roles_of(session, alice) == {}
    assert await _roles_of(session, bob) == {}


async def test_duplicate_mappings_give_409(session: AsyncSession) -> None:
    gremium, _member, board = await _gremium(session)
    # The 409 rolls the session back and expires the loaded rows, so build the
    # payloads before.
    member_dup, role_dup = _member_of("dup", gremium), _role_for("dup-role", board)
    svc = OidcMappingService(session)
    await svc.create_membership_mapping(member_dup, _ACTOR)
    with pytest.raises(ConflictError, match="already maps"):
        await svc.create_membership_mapping(member_dup, _ACTOR)
    await svc.create_role_mapping(role_dup, _ACTOR)
    with pytest.raises(ConflictError, match="already maps"):
        await svc.create_role_mapping(role_dup, _ACTOR)
    # The same group may link to another gremium.
    other, _, _ = await _gremium(session)
    await svc.create_membership_mapping(_member_of("dup", other), _ACTOR)


async def test_erasure_removes_memberships(session: AsyncSession) -> None:
    gremium, member, _ = await _gremium(session)
    row = await _principal(session, ["erase-me"])
    await OidcMappingService(session).create_membership_mapping(
        _member_of("erase-me", gremium), _ACTOR
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


async def test_global_group_mapping_has_no_gremium_column(session: AsyncSession) -> None:
    columns = await session.run_sync(
        lambda s: {c["name"] for c in inspect(s.connection()).get_columns("group_mapping")}
    )
    assert "gremium_id" not in columns

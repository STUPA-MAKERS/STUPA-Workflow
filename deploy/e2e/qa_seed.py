"""QA seed: one principal per role, each with a ready-made session cookie.

This exists for the manual/Playwright QA sweep against the local stack. It writes ONLY
identity rows — principals with their OIDC groups, the global group mappings, the
Gremium membership mappings and the Gremium role mappings — plus one signed session
cookie per role. Every piece of domain config (the
application type, the form, the flow, budgets, meetings) is created afterwards through
the REST API, so the QA data goes through the same validation as real data.

Minting a cookie with `create_principal_session` is the same trick `deploy/e2e/seed.py`
uses: it is the app's own signing function, not a backdoor, and it only runs here.

The IdP is the only source of global roles and Gremium memberships. The seed thus
writes no `role_assignment` and no `gremium_membership` by hand. It sets the group cache
`principal.oidc_groups`, which an OIDC login would fill. The RBAC resolver maps these
groups to the global roles at each request. The seed then calls the backend sync
`sync_all_memberships`, which writes the memberships from the Gremium membership
mappings and the Gremium role mappings. A later login or a later change of a mapping
gives the same rows.

The group `gremium-<gremium>` makes a person a member of that Gremium, with the default
Gremium role `member`. The group `gremium-<gremium>-<role>` gives a member a different
Gremium role. The role group alone makes nobody a member.

The Gremium memberships matter for voting: `vote.cast` eligibility comes from an active
membership whose Gremium role carries it, never from a global role.

If you log in through a real IdP (for example the local Keycloak of
`docker-compose.keycloak.yml`), put each user into the groups of `PEOPLE`. The sync
replaces the memberships at each login with the groups that the IdP sends.

Output: ``${E2E_ARTIFACTS}/qa.json`` with the cookie name and one cookie per role.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.db import get_sessionmaker
from app.modules.admin.membership_sync import sync_all_memberships
from app.modules.admin.models import (
    Gremium,
    GremiumMembershipMapping,
    GremiumRole,
    GremiumRoleMapping,
)
from app.modules.auth.models import GroupMapping, Principal, Role, RoleAssignment
from app.modules.auth.sessions import create_principal_session
from app.settings import get_settings

ARTIFACTS = pathlib.Path(os.environ.get("E2E_ARTIFACTS", "/artifacts"))

# The actor of the role assignments that an older version of this seed wrote.
ACTOR = "qa-seed"

# (sub, email, display name, global role key or None, gremium key or None, gremium role)
PEOPLE: list[tuple[str, str, str, str | None, str | None, str | None]] = [
    ("qa-admin", "admin@qa.test", "Alina Admin", "admin", "stupa", "vorstand"),
    ("qa-manager", "manager@qa.test", "Mara Manager", "manager", "stupa", "manager"),
    ("qa-finance", "finance@qa.test", "Fabio Finanzen", "finance", "asta", "member"),
    ("qa-protocol", "protocol@qa.test", "Pia Protokoll", "protocol", "stupa", "protokoll"),
    ("qa-member", "member@qa.test", "Mika Mitglied", "member", "stupa", "member"),
    # No global role and no membership: the "signed in but entitled to nothing" case,
    # which is what every RBAC gate has to hold against.
    ("qa-nobody", "nobody@qa.test", "Nils Ohnerolle", None, None, None),
]


def _role_group(role_key: str) -> str:
    """Return the OIDC group that gives a global role."""
    return f"role-{role_key}"


# The Gremium role that a member without a role mapping gets.
DEFAULT_GREMIUM_ROLE = "member"

# Custom Gremium roles that the seed creates in each Gremium of `PEOPLE` that uses them
# (D4). The forced roles (vorstand, manager, member) exist already. `protokoll` is the
# minute-taker: it can be assigned as keeper and write the minutes. The membership itself
# gives the read access to the meetings of the Gremium, so the role needs no read key.
SEED_GREMIUM_ROLES: dict[str, tuple[dict[str, str], list[str]]] = {
    "protokoll": ({"de": "Protokoll", "en": "Minute-taker"}, ["protocol.write"]),
}


def _membership_group(gremium_key: str) -> str:
    """Return the OIDC group that makes a person a member of a Gremium."""
    return f"gremium-{gremium_key}"


def _gremium_role_group(gremium_key: str, gremium_role_key: str) -> str:
    """Return the OIDC group that gives a member a role in a Gremium."""
    return f"gremium-{gremium_key}-{gremium_role_key}"


def _groups_of(
    role_key: str | None, gremium_key: str | None, gremium_role_key: str | None
) -> list[str]:
    """Return the OIDC groups of one person in `PEOPLE`."""
    groups: list[str] = []
    if role_key is not None:
        groups.append(_role_group(role_key))
    if gremium_key is not None:
        groups.append(_membership_group(gremium_key))
        role = gremium_role_key or DEFAULT_GREMIUM_ROLE
        if role != DEFAULT_GREMIUM_ROLE:
            groups.append(_gremium_role_group(gremium_key, role))
    return groups


# Each global group maps to one role. An OIDC login thus lands on the same role as the
# minted cookie.
GROUP_MAPPINGS = [
    (_role_group(key), key) for key in ("admin", "manager", "finance", "protocol", "member")
]

# Gremium keys. Each one gets the membership group `gremium-<gremium>`.
GREMIUM_MEMBERSHIP_MAPPINGS = sorted(
    {gremium_key for _, _, _, _, gremium_key, _ in PEOPLE if gremium_key is not None}
)

# (gremium key, gremium role key) for each role other than the default role. Each pair
# gets the role group `gremium-<gremium>-<role>`.
GREMIUM_ROLE_MAPPINGS = sorted(
    {
        (gremium_key, gremium_role_key)
        for _, _, _, _, gremium_key, gremium_role_key in PEOPLE
        if gremium_key is not None
        and gremium_role_key is not None
        and gremium_role_key != DEFAULT_GREMIUM_ROLE
    }
)


async def _roles_by_key(session) -> dict[str, uuid.UUID]:
    rows = (await session.execute(select(Role.key, Role.id))).all()
    return {key: rid for key, rid in rows}


async def _gremien_by_key(session) -> dict[str, uuid.UUID]:
    rows = (await session.execute(select(Gremium.slug, Gremium.id))).all()
    return {slug: gid for slug, gid in rows}


async def _gremium_role(session, gremium_id: uuid.UUID, key: str) -> uuid.UUID | None:
    return (
        await session.execute(
            select(GremiumRole.id).where(
                GremiumRole.gremium_id == gremium_id, GremiumRole.key == key
            )
        )
    ).scalar_one_or_none()


async def _ensure_seed_gremium_roles(session, gremien: dict[str, uuid.UUID]) -> None:
    """Create the custom Gremium roles of `SEED_GREMIUM_ROLES` where `PEOPLE` uses them."""
    for gremium_key, gremium_role_key in GREMIUM_ROLE_MAPPINGS:
        spec = SEED_GREMIUM_ROLES.get(gremium_role_key)
        gid = gremien.get(gremium_key)
        if spec is None or gid is None:
            continue
        if await _gremium_role(session, gid, gremium_role_key) is not None:
            continue
        name_i18n, permissions = spec
        session.add(
            GremiumRole(
                gremium_id=gid,
                key=gremium_role_key,
                name_i18n=name_i18n,
                permissions=list(permissions),
            )
        )
    await session.flush()


async def _ensure_principal(session, sub: str, email: str, name: str) -> Principal:
    row = (
        await session.execute(select(Principal).where(Principal.sub == sub))
    ).scalar_one_or_none()
    if row is None:
        row = Principal(sub=sub, email=email, display_name=name)
        session.add(row)
        await session.flush()
    return row


async def _drop_manual_assignments(session, principal_id) -> None:
    """Remove the role assignments that an older version of this seed wrote."""
    await session.execute(
        delete(RoleAssignment).where(
            RoleAssignment.principal_id == principal_id,
            RoleAssignment.granted_by == ACTOR,
        )
    )


async def _ensure_group_mappings(session, roles: dict[str, uuid.UUID]) -> None:
    for group, role_key in GROUP_MAPPINGS:
        role_id = roles.get(role_key)
        if role_id is None:
            continue
        existing = (
            await session.execute(
                select(GroupMapping.id).where(GroupMapping.oidc_group == group)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(GroupMapping(oidc_group=group, role_id=role_id))
    await session.flush()


async def _ensure_gremium_membership_mappings(
    session, gremien: dict[str, uuid.UUID]
) -> None:
    for gremium_key in GREMIUM_MEMBERSHIP_MAPPINGS:
        gid = gremien.get(gremium_key)
        if gid is None:
            continue
        group = _membership_group(gremium_key)
        existing = (
            await session.execute(
                select(GremiumMembershipMapping.id).where(
                    GremiumMembershipMapping.gremium_id == gid,
                    GremiumMembershipMapping.oidc_group == group,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(GremiumMembershipMapping(gremium_id=gid, oidc_group=group))
    await session.flush()


async def _ensure_gremium_role_mappings(session, gremien: dict[str, uuid.UUID]) -> None:
    for gremium_key, gremium_role_key in GREMIUM_ROLE_MAPPINGS:
        gid = gremien.get(gremium_key)
        if gid is None:
            continue
        grid = await _gremium_role(session, gid, gremium_role_key)
        if grid is None:
            continue
        group = _gremium_role_group(gremium_key, gremium_role_key)
        existing = (
            await session.execute(
                select(GremiumRoleMapping.id).where(
                    GremiumRoleMapping.gremium_role_id == grid,
                    GremiumRoleMapping.oidc_group == group,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(GremiumRoleMapping(gremium_role_id=grid, oidc_group=group))
    await session.flush()


async def main() -> None:
    settings = get_settings()
    maker = get_sessionmaker()
    cookies: dict[str, str] = {}
    subs: dict[str, str] = {}

    async with maker() as session:
        roles = await _roles_by_key(session)
        gremien = await _gremien_by_key(session)
        await _ensure_group_mappings(session, roles)
        await _ensure_gremium_membership_mappings(session, gremien)
        await _ensure_seed_gremium_roles(session, gremien)
        await _ensure_gremium_role_mappings(session, gremien)

        for sub, email, name, role_key, gremium_key, gremium_role_key in PEOPLE:
            principal = await _ensure_principal(session, sub, email, name)
            # The group cache that an OIDC login would fill.
            principal.oidc_groups = _groups_of(role_key, gremium_key, gremium_role_key)
            await _drop_manual_assignments(session, principal.id)

            label = sub.removeprefix("qa-")
            cookies[label] = await create_principal_session(
                session,
                secret=settings.session_secret,
                principal_id=principal.id,
                expires_at=datetime.now(UTC) + timedelta(days=30),
                refresh_token=None,
                id_token=None,
            )
            subs[label] = sub

        # The same sync that runs after each change of a Gremium mapping. It
        # writes the memberships of every principal from its OIDC groups.
        await session.flush()
        await sync_all_memberships(session)
        await session.commit()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "sessionCookieName": settings.session_cookie_name,
        "cookies": cookies,
        "subs": subs,
        "gremien": {k: str(v) for k, v in gremien.items()},
        "roles": {k: str(v) for k, v in roles.items()},
    }
    (ARTIFACTS / "qa.json").write_text(json.dumps(payload, indent=2))
    print("qa_seed: ok ->", ARTIFACTS / "qa.json")
    for label in cookies:
        print("  role:", label)


if __name__ == "__main__":
    asyncio.run(main())

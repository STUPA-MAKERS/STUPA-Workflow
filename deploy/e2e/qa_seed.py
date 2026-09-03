"""QA seed: one principal per role, each with a ready-made session cookie.

This exists for the manual/Playwright QA sweep against the local stack. It writes ONLY
identity rows — principals, role assignments, Gremium memberships and OIDC group
mappings — plus one signed session cookie per role. Every piece of domain config (the
application type, the form, the flow, budgets, meetings) is created afterwards through
the REST API, so the QA data goes through the same validation as real data.

Minting a cookie with `create_principal_session` is the same trick `deploy/e2e/seed.py`
uses: it is the app's own signing function, not a backdoor, and it only runs here.

The Gremium memberships matter for voting: `vote.cast` eligibility comes from an active
membership whose Gremium role carries it, never from a global role.

Output: ``${E2E_ARTIFACTS}/qa.json`` with the cookie name and one cookie per role.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import get_sessionmaker
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import GroupMapping, Principal, Role, RoleAssignment
from app.modules.auth.sessions import create_principal_session
from app.settings import get_settings

ARTIFACTS = pathlib.Path(os.environ.get("E2E_ARTIFACTS", "/artifacts"))

# (sub, email, display name, global role key or None, gremium key or None, gremium role)
PEOPLE: list[tuple[str, str, str, str | None, str | None, str | None]] = [
    ("qa-admin", "admin@qa.test", "Alina Admin", "admin", "stupa", "vorstand"),
    ("qa-manager", "manager@qa.test", "Mara Manager", "manager", "stupa", "manager"),
    ("qa-finance", "finance@qa.test", "Fabio Finanzen", "finance", "asta", "member"),
    ("qa-protocol", "protocol@qa.test", "Pia Protokoll", "protocol", "stupa", "member"),
    ("qa-member", "member@qa.test", "Mika Mitglied", "member", "stupa", "member"),
    # No global role and no membership: the "signed in but entitled to nothing" case,
    # which is what every RBAC gate has to hold against.
    ("qa-nobody", "nobody@qa.test", "Nils Ohnerolle", None, None, None),
]

# The Keycloak realm puts each user in exactly one of these groups. Mapping them here
# means an OIDC login lands on the same role as the minted cookie.
GROUP_MAPPINGS = [
    ("role-admin", "admin"),
    ("role-manager", "manager"),
    ("role-finance", "finance"),
    ("role-protocol", "protocol"),
    ("role-member", "member"),
]


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


async def _ensure_principal(session, sub: str, email: str, name: str) -> Principal:
    row = (
        await session.execute(select(Principal).where(Principal.sub == sub))
    ).scalar_one_or_none()
    if row is None:
        row = Principal(sub=sub, email=email, display_name=name)
        session.add(row)
        await session.flush()
    return row


async def _ensure_assignment(session, principal_id, role_id) -> None:
    existing = (
        await session.execute(
            select(RoleAssignment.id).where(
                RoleAssignment.principal_id == principal_id,
                RoleAssignment.role_id == role_id,
                RoleAssignment.gremium_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            RoleAssignment(
                principal_id=principal_id,
                role_id=role_id,
                granted_by="qa-seed",
                valid_from=datetime.now(UTC),
            )
        )
        await session.flush()


async def _ensure_membership(session, principal_id, gremium_id, gremium_role_id) -> None:
    existing = (
        await session.execute(
            select(GremiumMembership.id).where(
                GremiumMembership.principal_id == principal_id,
                GremiumMembership.gremium_id == gremium_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            GremiumMembership(
                principal_id=principal_id,
                gremium_id=gremium_id,
                gremium_role_id=gremium_role_id,
                valid_from=datetime.now(UTC) - timedelta(days=1),
            )
        )
        await session.flush()


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


async def main() -> None:
    settings = get_settings()
    maker = get_sessionmaker()
    cookies: dict[str, str] = {}
    subs: dict[str, str] = {}

    async with maker() as session:
        roles = await _roles_by_key(session)
        gremien = await _gremien_by_key(session)
        await _ensure_group_mappings(session, roles)

        for sub, email, name, role_key, gremium_key, gremium_role_key in PEOPLE:
            principal = await _ensure_principal(session, sub, email, name)
            if role_key is not None and role_key in roles:
                await _ensure_assignment(session, principal.id, roles[role_key])
            if gremium_key is not None and gremium_key in gremien:
                gid = gremien[gremium_key]
                grid = await _gremium_role(session, gid, gremium_role_key or "member")
                if grid is not None:
                    await _ensure_membership(session, principal.id, gid, grid)

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

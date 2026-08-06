"""Integration: an administrator revokes the agent token of another principal.

The test drives the real route function against a real Postgres. It checks the whole
chain: the grant appears in the admin list with a resolved owner name, the revoke writes
the audit entry, and the access token stops authenticating at once. The last check runs
through `app.deps.get_current_principal`, the function that every request uses.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from app import deps
from app.modules.audit.models import AuditEntry
from app.modules.auth import oauth_service
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.models import Role, RoleAssignment, RolePermission
from app.modules.auth.oauth_admin_router import (
    GrantListQuery,
    list_oauth_grants_admin,
    revoke_oauth_grant_admin,
)
from app.modules.auth.oauth_models import OAuthToken
from app.modules.auth.principal import Principal
from app.settings import load_settings
from app.shared.errors import NotFoundError

pytestmark = pytest.mark.integration

_CLIENT = "antragsplattform-mcp"
_REDIRECT = "http://127.0.0.1:7777/callback"
_VERIFIER = "v" * 64
_ACCESS_TTL = 3600
_REFRESH_TTL = 86400

SETTINGS = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123456",
    magic_link_secret="magic-link-secret-0",
    public_base_url="https://antrag.example",
)


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _challenge(verifier: str) -> str:
    d = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")


async def _agent_owner(session: AsyncSession) -> PrincipalRow:
    """Create a principal that holds `mcp.use`, so a token of it authenticates."""
    row = PrincipalRow(
        sub=f"sub-{uuid.uuid4()}",
        email="owner@example.de",
        display_name="Agent Owner",
        active=True,
    )
    session.add(row)
    role = Role(key=f"agent-{uuid.uuid4()}", name_i18n={"de": "Agent"})
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, permission="mcp.use"))
    session.add(RolePermission(role_id=role.id, permission="application.read"))
    session.add(RoleAssignment(principal_id=row.id, role_id=role.id))
    await session.flush()
    return row


async def _issue_token(session: AsyncSession, owner: PrincipalRow) -> str:
    code = await oauth_service.create_authorization_code(
        session,
        principal_id=owner.id,
        client_id=_CLIENT,
        redirect_uri=_REDIRECT,
        code_challenge=_challenge(_VERIFIER),
        scope="read",
        now=datetime.now(UTC),
        ttl_seconds=300,
        access_ttl_seconds=_ACCESS_TTL,
    )
    issued = await oauth_service.exchange_code(
        session,
        code=code,
        code_verifier=_VERIFIER,
        redirect_uri=_REDIRECT,
        client_id=_CLIENT,
        now=datetime.now(UTC),
        access_ttl=_ACCESS_TTL,
        refresh_ttl=_REFRESH_TTL,
    )
    await session.commit()
    return issued.access_token


def _request(token: str) -> Request:
    """Build the request the runtime sees: `Authorization: Bearer apat_…`."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/auth/me",
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )


def _admin_principal() -> Principal:
    return Principal(
        sub="admin-int",
        email="admin@example.de",
        roles=["member"],
        permissions={"admin.users"},
    )


async def _grant_id(session: AsyncSession, owner: PrincipalRow) -> uuid.UUID:
    return (
        await session.execute(
            select(OAuthToken.id).where(OAuthToken.principal_id == owner.id)
        )
    ).scalar_one()


async def test_admin_lists_and_revokes_the_grant_of_another_principal(
    session: AsyncSession,
) -> None:
    owner = await _agent_owner(session)
    token = await _issue_token(session, owner)

    # The token authenticates before the revoke.
    before = await deps.get_current_principal(_request(token), session, SETTINGS)
    assert before is not None and before.sub == owner.sub

    page = await list_oauth_grants_admin(
        session, _admin_principal(), GrantListQuery(principalId=owner.id)
    )
    assert page.total == 1
    item = page.items[0]
    assert item.principal_name == "Agent Owner"
    assert item.client_id == _CLIENT
    dumped = page.model_dump_json(by_alias=True)
    assert "hash" not in dumped and token not in dumped

    await revoke_oauth_grant_admin(item.id, session, _admin_principal())

    # The same check the runtime uses now refuses the token.
    after = await deps.get_current_principal(_request(token), session, SETTINGS)
    assert after is None
    assert await oauth_service.resolve_access_token(
        session, token=token, now=datetime.now(UTC)
    ) is None

    # The grant leaves the admin list and the audit log holds the revoke.
    empty = await list_oauth_grants_admin(session, _admin_principal(), GrantListQuery())
    assert empty.total == 0
    entry = (
        await session.execute(
            select(AuditEntry).where(AuditEntry.target_type == "oauth_token")
        )
    ).scalars().one()
    assert entry.action == "role_change"
    assert entry.actor == "admin-int"
    assert entry.data["event"] == "oauth_grant_revoke"
    assert entry.data["principalId"] == str(owner.id)


async def test_admin_revoke_of_an_unknown_grant_raises_not_found(
    session: AsyncSession,
) -> None:
    with pytest.raises(NotFoundError):
        await revoke_oauth_grant_admin(uuid.uuid4(), session, _admin_principal())


async def test_admin_revoke_is_idempotent(session: AsyncSession) -> None:
    owner = await _agent_owner(session)
    token = await _issue_token(session, owner)
    grant_id = await _grant_id(session, owner)

    await revoke_oauth_grant_admin(grant_id, session, _admin_principal())
    await revoke_oauth_grant_admin(grant_id, session, _admin_principal())

    assert await oauth_service.resolve_access_token(
        session, token=token, now=datetime.now(UTC)
    ) is None
    entries = (
        await session.execute(
            select(AuditEntry).where(AuditEntry.target_id == str(grant_id))
        )
    ).scalars().all()
    # The second call revokes nothing, so it writes no second entry.
    assert len(entries) == 1

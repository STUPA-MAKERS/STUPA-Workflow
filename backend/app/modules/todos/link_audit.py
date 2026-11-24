"""The audit entries of an added or a removed link (§F/collaboration/links/002923).

Each entry names both ends by kind and id, a Paperless end also by the number of its
document, and the grant of an OAuth token (``Principal.grant``), so an admin finds the
links of a token and revokes it. A link from the browser has no grant.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record
from app.modules.auth.principal import Principal
from app.modules.paperless.links import LINK_KIND as PAPERLESS
from app.modules.paperless.links import document_number
from app.modules.todos.models import Link


def end_data(kind: str, target_id: uuid.UUID) -> dict[str, Any]:
    """One end of a link for the audit ``data``, a Paperless end with its number."""
    number = {"number": document_number(target_id)} if kind == PAPERLESS else {}
    return {"kind": kind, "id": str(target_id), **number}


def link_data(link: Link, principal: Principal) -> dict[str, Any]:
    """The ``data`` of a link entry: both ends and the grant of a token."""
    grant = {"grant": dict(principal.grant)} if principal.grant is not None else {}
    return {
        "a": end_data(link.a_kind, link.a_id),
        "b": end_data(link.b_kind, link.b_id),
        **grant,
    }


async def audit_link(
    session: AsyncSession, action: AuditAction, link: Link, principal: Principal
) -> None:
    """Write the entry ``link_add`` or ``link_remove`` of ``link``; no commit.

    The session flushes first, because the id of a new link comes from the database.
    """
    await session.flush()
    await record(
        session,
        actor=principal.sub,
        action=action,
        target_type="link",
        target_id=str(link.id),
        data=link_data(link, principal),
    )

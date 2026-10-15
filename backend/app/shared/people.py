"""A person on the wire: ``PersonRef`` and its batch resolver.

A person reference names an account by id and display name, never by ``sub`` and
never by e-mail unless the reference is the only name left. The display name is the
name of the account, else its e-mail. An erased account (no name and no e-mail) or
an id without a row gives ``principalId: null, displayName: null``; the frontend
shows that as "Gelöschte Person".
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow


class PersonRef(BaseModel):
    """A person on a ticket, a note or an event. null/null is a deleted person."""

    model_config = ConfigDict(populate_by_name=True)

    principal_id: UUID | None = Field(default=None, serialization_alias="principalId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")


DELETED_PERSON = PersonRef(principal_id=None, display_name=None)


def person_of(principal_id: UUID, display_name: str | None, email: str | None) -> PersonRef:
    """Build the reference of one account row (deleted when it has no name left)."""
    name = display_name or email
    if not name:
        return DELETED_PERSON
    return PersonRef(principal_id=principal_id, display_name=name)


async def person_refs(session: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, PersonRef]:
    """Resolve principal ids to references in one query.

    An id without a row maps to the deleted person, so a caller can index the result
    with every id it passed.
    """
    wanted = {pid for pid in ids if pid is not None}
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
                PrincipalRow.id.in_(wanted)
            )
        )
    ).all()
    found = {pid: person_of(pid, name, email) for pid, name, email in rows}
    return {pid: found.get(pid, DELETED_PERSON) for pid in wanted}

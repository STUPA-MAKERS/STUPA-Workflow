"""Display identity of a principal that follows an account merge.

An admin can merge an old principal into a new one (``admin/principal_merge.py``).
The merge rewrites the references, but some stay on the old ``sub`` or id: the
append-only audit log and its ``data``, and any row that a request wrote while the
merge ran. Every name lookup goes through this module, so such a reference shows
the name of the principal that the old one was merged into.

The merge never targets a merged principal and re-points the earlier merges into
the old one, so one join step is enough.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Row, Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.auth.models import Principal as PrincipalRow


@dataclass(frozen=True, slots=True)
class PrincipalRef:
    """The principal that a display shows for a stored ``sub`` or id."""

    id: UUID
    display_name: str | None
    email: str | None
    # The name of the stored principal itself, before the merge step. A display that
    # names the account as a target (the audit target label, an id in the audit data)
    # uses it, so the merge entry names the old account and not the new one.
    own_name: str | None = None

    @property
    def name(self) -> str | None:
        """The display name, else the email. None for an anonymized account."""
        return self.display_name or self.email

    @property
    def label(self) -> str | None:
        """The own name of the stored account, else the name it was merged into."""
        return self.own_name or self.name


_RefSelect = Select[str, UUID, str | None, str | None, UUID, str | None, str | None]


def _select() -> _RefSelect:
    shown = aliased(PrincipalRow)
    return select(
        PrincipalRow.sub,
        PrincipalRow.id,
        PrincipalRow.display_name,
        PrincipalRow.email,
        shown.id,
        shown.display_name,
        shown.email,
    ).outerjoin(shown, shown.id == PrincipalRow.merged_into)


def _ref(
    row: Row[str, UUID, str | None, str | None, UUID, str | None, str | None],
) -> PrincipalRef:
    _sub, pid, dn, em, tid, tdn, tem = row
    own = dn or em
    if tid is not None:
        return PrincipalRef(id=tid, display_name=tdn, email=tem, own_name=own)
    return PrincipalRef(id=pid, display_name=dn, email=em, own_name=own)


async def refs_by_sub(
    session: AsyncSession, subs: Iterable[str | None]
) -> dict[str, PrincipalRef]:
    """Map each known ``sub`` to the principal that a display shows. One query."""
    wanted = {s for s in subs if s}
    if not wanted:
        return {}
    rows = (await session.execute(_select().where(PrincipalRow.sub.in_(wanted)))).all()
    return {row[0]: _ref(row) for row in rows}


async def refs_by_id(
    session: AsyncSession, ids: Iterable[UUID]
) -> dict[UUID, PrincipalRef]:
    """Map each known principal id to the principal that a display shows. One query."""
    wanted = set(ids)
    if not wanted:
        return {}
    rows = (await session.execute(_select().where(PrincipalRow.id.in_(wanted)))).all()
    return {row[1]: _ref(row) for row in rows}

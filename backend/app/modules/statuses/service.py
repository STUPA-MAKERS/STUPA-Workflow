"""Read and replace a status list (F/administration/admin/003035-003038).

`StatusReader` gives the other modules the phases of the statuses, so their code never
names a status key. `StatusWriter` replaces a list and moves the elements of a removed
status to its replacement. Neither commits; the admin service records the revision.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import (
    ColumnElement,
    Select,
    TableClause,
    column,
    delete,
    func,
    select,
    table,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.statuses.models import StatusDef
from app.modules.statuses.rules import StatusItem, list_errors, replacement_errors
from app.modules.statuses.schemas import StatusIn, StatusListOut, StatusOut
from app.shared.errors import ConflictError, ValidationProblem

#: The table of the elements of each list and its status column. The statuses module is a
#: layer below the element modules, so it names the tables and never imports them.
ELEMENT_TABLES: dict[str, str] = {"order": "purchase_order", "event": "event"}


def _element_table(kind: str) -> TableClause:
    """Return the table clause of the elements of a list."""
    return table(ELEMENT_TABLES[kind], column("status"))


def keys_in(kind: str, *phases: str) -> Select[str]:
    """Select the keys of the statuses of a list in these phases, for an SQL ``IN``."""
    return select(StatusDef.key).where(StatusDef.list_kind == kind, StatusDef.phase.in_(phases))


def in_phase(
    status: ColumnElement[str] | InstrumentedAttribute[str], kind: str, *phases: str
) -> ColumnElement[bool]:
    """Build the condition that a status column holds a status of these phases."""
    return status.in_(keys_in(kind, *phases))


@dataclass(frozen=True, slots=True)
class StatusReader:
    """The reads of the status lists, bound to an ``AsyncSession``."""

    session: AsyncSession

    async def rows(self, kind: str) -> Sequence[StatusDef]:
        """Return the statuses of a list in their order."""
        result = await self.session.scalars(
            select(StatusDef).where(StatusDef.list_kind == kind).order_by(StatusDef.position)
        )
        return result.all()

    async def get(self, kind: str, key: str) -> StatusDef | None:
        """Return one status of a list, or None for an unknown key."""
        return await self.session.scalar(
            select(StatusDef).where(StatusDef.list_kind == kind, StatusDef.key == key)
        )

    async def require(self, kind: str, key: str) -> StatusDef:
        """Return one status of a list.

        Raises:
            ValidationProblem: ``status_unknown`` (422) for a key that is not in the list.
        """
        row = await self.get(kind, key)
        if row is None:
            raise ValidationProblem(
                "The status is not in the list.",
                code="status_unknown",
                errors=[{"field": "status", "msg": key}],
            )
        return row

    async def start_key(self, kind: str) -> str:
        """Return the key of the start status of a list."""
        key = await self.session.scalar(
            select(StatusDef.key).where(StatusDef.list_kind == kind, StatusDef.is_start)
        )
        if key is None:  # pragma: no cover - the migration and the writer keep one start
            raise ConflictError("The list has no start status.", code="status_list_empty")
        return key

    async def phases(self, kind: str) -> dict[str, str]:
        """Return the phase of each key of a list."""
        return {row.key: row.phase for row in await self.rows(kind)}

    async def usage(self, kind: str) -> dict[str, int]:
        """Count the elements of each status of a list; a list without elements yet has none."""
        if kind not in ELEMENT_TABLES:
            return {}
        elements = _element_table(kind)
        result = await self.session.execute(
            select(elements.c.status, func.count()).group_by(elements.c.status)
        )
        return dict(result.tuples().all())

    async def out(self, kind: str, *, with_usage: bool = False) -> StatusListOut:
        """Return a list as its answer."""
        used = await self.usage(kind) if with_usage else {}
        return StatusListOut(
            kind=kind,  # pyright: ignore[reportArgumentType]
            statuses=tuple(
                StatusOut(
                    key=row.key,
                    name=dict(row.name),
                    tone=row.tone,  # pyright: ignore[reportArgumentType]
                    phase=row.phase,  # pyright: ignore[reportArgumentType]
                    start=row.is_start,
                    setsDate=row.sets_date,  # pyright: ignore[reportArgumentType]
                    used=used.get(row.key, 0),
                )
                for row in await self.rows(kind)
            ),
        )


@dataclass(frozen=True, slots=True)
class StatusWriter:
    """The replace of a status list, bound to an ``AsyncSession``."""

    session: AsyncSession

    async def replace(
        self,
        kind: str,
        statuses: Sequence[StatusIn],
        replacements: Mapping[str, str],
        *,
        locked: frozenset[str] = frozenset(),
    ) -> dict[str, int]:
        """Replace a list and move the elements of each removed status in use.

        ``locked`` holds the keys that a setting elsewhere names (the flow), so they must
        stay. The answer counts the moved elements per removed key.

        Raises:
            ValidationProblem: ``status_list_invalid`` (422) for a list that breaks a rule.
            ConflictError: ``status_in_use`` (409) for a removed key in use without a
                replacement, ``status_in_flow`` (409) for a removed key in ``locked``.
        """
        items = [StatusItem(s.key, s.phase, s.start, s.sets_date) for s in statuses]
        keys = [s.key for s in statuses]
        reader = StatusReader(self.session)
        before = [row.key for row in await reader.rows(kind)]
        removed = [key for key in before if key not in keys]
        errors = [*list_errors(kind, items), *replacement_errors(removed, replacements, keys)]
        if errors:
            raise ValidationProblem(
                "The status list breaks a rule.", code="status_list_invalid", errors=errors
            )
        if blocked := [key for key in removed if key in locked]:
            raise ConflictError(
                f"A transition of the flow names the status {blocked[0]!r}.",
                code="status_in_flow",
            )
        used = await reader.usage(kind)
        if missing := [key for key in removed if used.get(key) and key not in replacements]:
            raise ConflictError(
                f"Elements have the status {missing[0]!r}; name a replacement.",
                code="status_in_use",
            )
        moved = {old: used[old] for old in removed if used.get(old)}
        for old in moved:
            elements = _element_table(kind)
            await self.session.execute(
                update(elements).where(elements.c.status == old).values(status=replacements[old])
            )
        await self.session.execute(delete(StatusDef).where(StatusDef.list_kind == kind))
        await self.session.flush()
        self.session.add_all(
            [
                StatusDef(
                    list_kind=kind,
                    key=s.key,
                    position=position,
                    name=dict(s.name),
                    tone=s.tone,
                    phase=s.phase,
                    is_start=s.start,
                    sets_date=s.sets_date,
                )
                for position, s in enumerate(statuses)
            ]
        )
        await self.session.flush()
        return moved

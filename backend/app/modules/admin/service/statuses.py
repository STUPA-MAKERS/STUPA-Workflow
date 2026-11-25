"""The admin write of a status list (F/administration/admin/003035, 003038).

The save replaces the whole list, moves the elements of each removed status to its
replacement and records a config revision with its audit entry. A status that a
transition of the active flow names (``offerOnOrderStatus``, 002931) must stay.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.config_revision.service import ENTITY_STATUS_LIST, ConfigRevisionService
from app.modules.flow.models import FlowVersion, Transition
from app.modules.statuses.schemas import StatusIn, StatusListOut, StatusListSet
from app.modules.statuses.service import StatusReader, StatusWriter


def snapshot_of(out: StatusListOut) -> dict[str, Any]:
    """Return the restorable snapshot of a list: its statuses without the counts."""
    return {
        "statuses": [status.model_dump(by_alias=True, exclude={"used"}) for status in out.statuses]
    }


@dataclass(frozen=True, slots=True)
class StatusListAdmin:
    """The admin reads and the save of the status lists, bound to an ``AsyncSession``."""

    session: AsyncSession

    async def get(self, kind: str) -> StatusListOut:
        """Return a list with the number of elements of each status."""
        return await StatusReader(self.session).out(kind, with_usage=True)

    async def _flow_keys(self, kind: str) -> frozenset[str]:
        """Return the keys that a transition of the active flow names."""
        if kind != "order":
            return frozenset()
        result = await self.session.scalars(
            select(Transition.offer_on_order_status)
            .join(FlowVersion, FlowVersion.id == Transition.flow_version_id)
            .where(FlowVersion.active, Transition.offer_on_order_status.is_not(None))
        )
        return frozenset(key for key in result.all() if key)

    async def save(
        self,
        kind: str,
        payload: StatusListSet,
        actor: str,
        *,
        action: AuditAction = AuditAction.CONFIG_CHANGE,
        extra_data: Mapping[str, Any] | None = None,
    ) -> StatusListOut:
        """Replace a list and record the revision. The caller commits.

        Raises:
            ValidationProblem: ``status_list_invalid`` (422).
            ConflictError: ``status_in_use`` or ``status_in_flow`` (409).
        """
        await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtext('status_def'))"))
        moved = await StatusWriter(self.session).replace(
            kind, payload.statuses, payload.replacements, locked=await self._flow_keys(kind)
        )
        out = await self.get(kind)
        await ConfigRevisionService(self.session).record(
            entity_type=ENTITY_STATUS_LIST,
            entity_id=kind,
            snapshot=snapshot_of(out),
            actor=actor,
            action=action,
            extra_data={
                **(extra_data or {}),
                **(
                    {
                        "moved": [
                            {"from": old, "to": payload.replacements[old], "count": n}
                            for old, n in moved.items()
                        ]
                    }
                    if moved
                    else {}
                ),
            },
        )
        return out

    async def restore(
        self,
        kind: str,
        statuses: Sequence[StatusIn],
        actor: str,
        *,
        action: AuditAction,
        extra_data: Mapping[str, Any] | None,
    ) -> StatusListOut:
        """Save the list of a snapshot again; a removed status in use refuses it (409)."""
        return await self.save(
            kind,
            StatusListSet(statuses=tuple(statuses)),
            actor,
            action=action,
            extra_data=extra_data,
        )

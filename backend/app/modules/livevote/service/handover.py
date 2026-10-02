"""Handover of the protocol keeper during a live meeting (Z3, O1, O20).

A meeting keeps its minutes in periods (`ProtocolKeeperPeriod`). The start of the
meeting opens the first period for the protokollant. A handover hands the minutes
to another member:

* `now` ends the running period and opens the next one at once.
* `next_item` plans the next period. The next forward move of the current agenda
  item starts it, in the same transaction as the move. A new planned handover
  replaces the old one. The last agenda item has no next item (409).

The close of the meeting ends the running period and drops the planned one.

`meeting.protokollant_id` always names the keeper of the running period. The rights
that follow the keeper therefore move with the handover: the write access
(`can_write`) and the vote management with the change of the agenda item
(`can_manage_votes`).

Rules of the handover route: the meeting is `live` (409 `meeting_not_live`). The
caller manages the meeting (`can_manage`) or is the current keeper (403). The new
keeper is an active member of the gremium (403) with the gremium permission
`protocol.write` (O20: 422 `protokollant_needs_protocol_write`). Every handover,
every discard and every start of a planned period writes `protokollant_handover`
and sends `meeting_state`. The start of a planned period checks the new keeper
again (O20). When the check fails, the plan goes away (audit mode `cancel`) and
the running keeper stays.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.modules.admin.gremium_roles import gremium_member_ids
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.agenda_service import agenda_order
from app.modules.livevote.keepers import KEEPER_PERMISSION, keeper_principal_ids
from app.modules.livevote.models import Meeting, MeetingAgendaItem, ProtocolKeeperPeriod
from app.modules.livevote.schemas import HandoverMode, MeetingOut
from app.modules.livevote.service.permissions import PermissionOps
from app.modules.livevote.service.votes import VoteReadOps
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem

# The audit mode of a planned period that a move of the agenda item started.
_MODE_ACTIVATE = "activate"
# The audit mode of a discarded planned handover.
_MODE_CANCEL = "cancel"


class HandoverOps(PermissionOps, VoteReadOps):
    """Periods of the protocol keeper: start, handover, activation and close."""

    async def check_keeper(self, gremium_id: UUID, principal_id: UUID) -> PrincipalRow:
        """Validate a new protocol keeper of the gremium (O20).

        Raises:
            NotFoundError: The principal does not exist.
            ForbiddenError: The principal is not an active member of the gremium.
            ValidationProblem: The gremium role of the principal does not grant
                `protocol.write` (`protokollant_needs_protocol_write`).
        """
        row = await self.session.get(PrincipalRow, principal_id)
        if row is None:
            raise NotFoundError(f"principal {principal_id} not found")
        if gremium_id not in await gremium_member_ids(self.session, row.sub):
            raise ForbiddenError("protokollant must be an active member of the committee")
        if principal_id not in await keeper_principal_ids(self.session, gremium_id):
            raise ValidationProblem(
                f"the protokollant needs the committee permission {KEEPER_PERMISSION}",
                code="protokollant_needs_protocol_write",
            )
        return row

    async def _is_valid_keeper(self, gremium_id: UUID, principal_id: UUID) -> bool:
        """Return True when `check_keeper` accepts the principal (O20)."""
        try:
            await self.check_keeper(gremium_id, principal_id)
        except (NotFoundError, ForbiddenError, ValidationProblem):
            return False
        return True

    async def can_hand_over(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who hands the minutes over: the meeting manager or the current keeper.

        The keeper path is scope-capped like every other keeper path: a token
        without `protocol.write` in its scope cannot use it.
        """
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        return principal.scope_allows(KEEPER_PERMISSION) and await self._is_protokollant(
            meeting, principal
        )

    async def _period(self, meeting_id: UUID, *, planned: bool) -> ProtocolKeeperPeriod | None:
        """Return the planned or the running period of a meeting, or `None`."""
        stmt = select(ProtocolKeeperPeriod).where(ProtocolKeeperPeriod.meeting_id == meeting_id)
        if planned:
            stmt = stmt.where(ProtocolKeeperPeriod.from_at.is_(None))
        else:
            stmt = stmt.where(
                ProtocolKeeperPeriod.from_at.is_not(None), ProtocolKeeperPeriod.to_at.is_(None)
            )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _agenda_ids(self, meeting_id: UUID) -> list[UUID]:
        """Return the ids of the agenda items of a meeting in agenda order."""
        return list(
            (
                await self.session.execute(
                    select(MeetingAgendaItem.id)
                    .where(MeetingAgendaItem.meeting_id == meeting_id)
                    .order_by(*agenda_order())
                )
            )
            .scalars()
            .all()
        )

    async def _end_running(self, meeting: Meeting, now: datetime, to_item: UUID | None) -> None:
        """End the running period at `now` (never before its start) and flush."""
        running = await self._period(meeting.id, planned=False)
        if running is None:
            return
        start = running.from_at or now
        running.to_at = max(now, start)
        running.to_agenda_item_id = to_item
        await self.session.flush()

    async def _drop_planned(self, meeting_id: UUID) -> ProtocolKeeperPeriod | None:
        """Delete the planned period, flush, and return it, or `None` without one."""
        planned = await self._period(meeting_id, planned=True)
        if planned is not None:
            await self.session.delete(planned)
            await self.session.flush()
        return planned

    async def open_first_period(self, meeting: Meeting, actor: str, now: datetime) -> None:
        """Open the first period for the protokollant on the start of the meeting.

        The method does nothing without a protokollant or when a period runs already.
        """
        if meeting.protokollant_id is None:
            return
        if await self._period(meeting.id, planned=False) is not None:
            return
        self.session.add(
            ProtocolKeeperPeriod(
                meeting_id=meeting.id,
                principal_id=meeting.protokollant_id,
                from_at=now,
                from_agenda_item_id=meeting.current_agenda_item_id,
                handed_over_by=actor,
            )
        )
        await self.session.flush()

    async def close_periods(self, meeting: Meeting, now: datetime) -> None:
        """End the running period and drop the planned one on the close."""
        await self._end_running(meeting, now, meeting.current_agenda_item_id)
        await self._drop_planned(meeting.id)

    async def switch_now(
        self, meeting: Meeting, principal_id: UUID, actor: str, now: datetime
    ) -> None:
        """Hand the minutes over at once: end the running period and open the next one.

        A planned handover goes away. The new period starts at the current agenda
        item, and the running one ends there.
        """
        await self._drop_planned(meeting.id)
        await self._end_running(meeting, now, meeting.current_agenda_item_id)
        self.session.add(
            ProtocolKeeperPeriod(
                meeting_id=meeting.id,
                principal_id=principal_id,
                from_at=now,
                from_agenda_item_id=meeting.current_agenda_item_id,
                handed_over_by=actor,
            )
        )
        meeting.protokollant_id = principal_id
        await self.session.flush()

    async def activate_planned(
        self,
        meeting: Meeting,
        old_item: UUID | None,
        new_item: UUID | None,
        actor: str,
        now: datetime,
    ) -> bool:
        """Start the planned period on a forward move of the current agenda item.

        A move is forward when the new item comes after the old one in the agenda
        order, or when no item was current before. A move back, a repeat of the
        same item, and a clear of the item keep the planned period.

        The method checks the planned keeper again before the start (O20), because
        the membership or the gremium role can change after the plan. When the
        check fails, the method deletes the planned period, keeps the running one
        and writes a `protokollant_handover` entry with the mode `cancel`.

        Returns:
            True when the method started a planned period.
        """
        if new_item is None or new_item == old_item:
            return False
        planned = await self._period(meeting.id, planned=True)
        if planned is None:
            return False
        if old_item is not None:
            order = await self._agenda_ids(meeting.id)
            if old_item in order and order.index(new_item) <= order.index(old_item):
                return False
        if not await self._is_valid_keeper(meeting.gremium_id, planned.principal_id):
            target = planned.principal_id
            await self._drop_planned(meeting.id)
            await self._audit_handover(
                meeting,
                actor,
                mode=_MODE_CANCEL,
                previous=meeting.protokollant_id,
                target=target,
            )
            return False
        previous = meeting.protokollant_id
        await self._end_running(meeting, now, old_item)
        planned.from_at = now
        planned.from_agenda_item_id = new_item
        meeting.protokollant_id = planned.principal_id
        await self.session.flush()
        await self._audit_handover(
            meeting,
            actor,
            mode=_MODE_ACTIVATE,
            previous=previous,
            target=planned.principal_id,
        )
        return True

    async def _audit_handover(
        self,
        meeting: Meeting,
        actor: str,
        *,
        mode: str,
        previous: UUID | None,
        target: UUID | None,
    ) -> None:
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.PROTOKOLLANT_HANDOVER,
            target_type="meeting",
            target_id=str(meeting.id),
            data={
                "gremiumId": str(meeting.gremium_id),
                "mode": mode,
                "from": None if previous is None else str(previous),
                "to": None if target is None else str(target),
                "agendaItemId": (
                    None
                    if meeting.current_agenda_item_id is None
                    else str(meeting.current_agenda_item_id)
                ),
            },
        )

    async def _live_for_handover(self, meeting_id: UUID, principal: Principal) -> Meeting:
        """Lock the meeting row and check the state and the right of the caller.

        Raises:
            NotFoundError: The meeting does not exist.
            ConflictError: The meeting is not live (`meeting_not_live`).
            ForbiddenError: The caller neither manages the meeting nor keeps the
                minutes now.
        """
        # The row lock serializes the handover with the close and the move of the
        # agenda item, which both change the periods too.
        meeting = await self._get(meeting_id, for_update=True)
        if not await self.can_hand_over(meeting, principal):
            raise ForbiddenError("only the session lead or the protokollant hands over")
        if meeting.status != "live":
            raise ConflictError(
                "the minutes are handed over only while the meeting is live",
                code="meeting_not_live",
            )
        return meeting

    async def hand_over(
        self, meeting_id: UUID, target: UUID, mode: HandoverMode, principal: Principal
    ) -> MeetingOut:
        """Hand the minutes over to `target`, now or from the next agenda item.

        Raises:
            ConflictError: The meeting is not live (`meeting_not_live`), the target
                keeps the minutes already (`already_protokollant`), or `next_item`
                has no next agenda item (`no_next_item`).
            ForbiddenError: The caller may not hand over, or the target is not an
                active member of the gremium.
            ValidationProblem: The target lacks `protocol.write` (O20).
        """
        meeting = await self._live_for_handover(meeting_id, principal)
        await self.check_keeper(meeting.gremium_id, target)
        if target == meeting.protokollant_id:
            raise ConflictError(
                "this member keeps the minutes already", code="already_protokollant"
            )
        now = datetime.now(UTC)
        previous = meeting.protokollant_id
        if mode == "now":
            await self.switch_now(meeting, target, principal.sub, now)
        else:
            order = await self._agenda_ids(meeting.id)
            current = meeting.current_agenda_item_id
            if not order or (current is not None and current == order[-1]):
                raise ConflictError(
                    "the current agenda item is the last one — hand over now instead",
                    code="no_next_item",
                )
            await self._drop_planned(meeting.id)
            self.session.add(
                ProtocolKeeperPeriod(
                    meeting_id=meeting.id, principal_id=target, handed_over_by=principal.sub
                )
            )
            await self.session.flush()
        await self._audit_handover(
            meeting, principal.sub, mode=mode, previous=previous, target=target
        )
        return await self._commit_and_publish(meeting, principal)

    async def cancel_handover(self, meeting_id: UUID, principal: Principal) -> MeetingOut:
        """Discard the planned handover of a live meeting.

        Raises:
            ConflictError: The meeting is not live (`meeting_not_live`).
            ForbiddenError: The caller may not hand over.
            NotFoundError: The meeting has no planned handover
                (`no_planned_handover`).
        """
        meeting = await self._live_for_handover(meeting_id, principal)
        planned = await self._drop_planned(meeting.id)
        if planned is None:
            raise NotFoundError(
                "the meeting has no planned handover", code="no_planned_handover"
            )
        await self._audit_handover(
            meeting,
            principal.sub,
            mode=_MODE_CANCEL,
            previous=meeting.protokollant_id,
            target=planned.principal_id,
        )
        return await self._commit_and_publish(meeting, principal)

    async def _commit_and_publish(self, meeting: Meeting, principal: Principal) -> MeetingOut:
        """Commit, build the `MeetingOut` of the caller and send `meeting_state`."""
        await self.session.commit()
        votes = (await self._votes_for([meeting.id], principal)).get(meeting.id, [])
        out = await self._emit(
            meeting, principal, protocol_id=await self._protocol_id(meeting.id), votes=votes
        )
        if self.publisher is not None:
            await self.publisher.meeting_state(out)
        return out

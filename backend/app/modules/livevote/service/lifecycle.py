"""Meeting lifecycle: create, patch (planned to live to closed), broadcast, delete.

The status runs only forward: ``planned`` to ``live`` to ``closed`` (F9, O13). A
repeat of the current status is a no-op. Every other change gives 409
``invalid_status_transition``. A meeting that does not take place is deleted, not
closed.

The lifecycle also drives the periods of the protocol keeper (Z3, see
``handover``): the start opens the first period, a forward move of the current
agenda item starts a planned handover, a new protokollant of a live meeting is a
handover ``now``, and the close ends the running period.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.livevote.guests import GuestEvents, GuestService
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.livevote.schemas import MeetingCreate, MeetingOut, MeetingPatch
from app.modules.livevote.service.handover import HandoverOps
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteOut
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

# The only status changes of a meeting (F9, O13). A repeat of the current status is a
# no-op and not in this set.
_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {("planned", "live"), ("live", "closed")}
)

# The planning fields that MEETING_UPDATE records, as (model attribute, JSON key).
_AUDITED_FIELDS: tuple[tuple[str, str], ...] = (
    ("status", "status"),
    ("date", "date"),
    ("start_time", "startTime"),
    ("end_time", "endTime"),
    ("protokollant_id", "protokollantId"),
)


def _snapshot(meeting: Meeting) -> dict[str, str | None]:
    """Return the audited planning values of a meeting as JSON-safe strings."""
    out: dict[str, str | None] = {}
    for attr, key in _AUDITED_FIELDS:
        value: Any = getattr(meeting, attr)
        out[key] = None if value is None else str(value)
    return out


class LifecycleOps(HandoverOps):
    """Create/patch/delete meetings and broadcast state changes."""

    async def create(self, payload: MeetingCreate, principal: Principal) -> MeetingOut:
        """Create a meeting in status ``planned``.

        Only a meeting manager (``session.manage``) may create a meeting.
        """
        if not await self.can_manage(payload.gremium_id, principal):
            raise ForbiddenError("not allowed to create meetings for this committee")
        protokollant_id = await self._resolve_protokollant(
            payload.gremium_id, payload.protokollant_id
        )
        meeting = Meeting(
            gremium_id=payload.gremium_id,
            title=payload.title,
            date=payload.date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            status="planned",
            created_by=principal.sub,
            protokollant_id=protokollant_id,
            public_join=payload.public_join,
            guests_mode=payload.guests_mode,
        )
        if payload.public_join:
            # #17: the join link exists from the start, so it can go into the invitation.
            await GuestService(self.session).ensure_code(meeting)
        self.session.add(meeting)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.MEETING_CREATE,
            target_type="meeting",
            target_id=str(meeting.id),
            data={
                "gremiumId": str(meeting.gremium_id),
                **_snapshot(meeting),
                "publicJoin": meeting.public_join,
                "guestsMode": meeting.guests_mode,
            },
        )
        await self.session.commit()
        return await self._emit(meeting, principal)

    async def _resolve_protokollant(
        self, gremium_id: UUID, protokollant_id: UUID | None
    ) -> UUID | None:
        """Validate the protokollant: an active member with ``protocol.write`` (O20).

        The rule applies to a new assignment only. A protokollant who lost
        ``protocol.write`` after the assignment can still start the meeting.
        """
        if protokollant_id is None:
            return None
        await self.check_keeper(gremium_id, protokollant_id)
        return protokollant_id

    async def patch(
        self, meeting_id: UUID, payload: MeetingPatch, principal: Principal
    ) -> MeetingOut:
        """Apply control and planning changes, then broadcast ``meeting_state``.

        RBAC works per field. Status and active application need ``canWrite``
        (protokollant or manager). Date, time and the protokollant assignment need
        ``canManage`` (meeting manager).

        The start (``planned`` to ``live``) sets ``started_at`` once. The close (``live``
        to ``closed``) sets ``closed_at`` and cancels the draft votes of the meeting in
        the same transaction, then sends ``vote_cancelled`` after the commit. A status
        change or a planning change writes ``meeting_update`` (F12).

        Z3: the start opens the first keeper period, and the close ends the running
        one. A forward move of the current agenda item starts a planned handover. A
        new protokollant of a live meeting is a handover ``now``. Each handover writes
        ``protokollant_handover`` instead of a protokollant change in
        ``meeting_update``. The same protokollant again is a no-op. A new
        protokollant needs ``protocol.write`` in the gremium (O20, 422).

        Raises:
            ConflictError: The status change is not ``planned`` to ``live`` or ``live``
                to ``closed`` (``invalid_status_transition``), the meeting still has an
                open vote on close (``open_vote``), the start has no protokollant, or
                the meeting is closed and the patch changes its planning.
        """
        # #17: public participation and the guest mode are planning values of the lead.
        wants_public = payload.public_join is not None or payload.guests_mode is not None
        wants_manage = (
            "date" in payload.model_fields_set
            or "start_time" in payload.model_fields_set
            or "end_time" in payload.model_fields_set
            or "protokollant_id" in payload.model_fields_set
            or wants_public
        )
        wants_write = payload.status is not None or payload.active_application_id is not None
        wants_now = "current_agenda_item_id" in payload.model_fields_set
        # A status change locks the meeting row. The open of a vote takes the same
        # lock, so the open-vote check below and the close cannot race (O12). A move
        # of the agenda item and a protokollant change can change the keeper periods
        # (Z3), so they take the lock too, as the handover route does.
        meeting = await self._get(
            meeting_id,
            for_update=(
                payload.status is not None
                or wants_now
                or "protokollant_id" in payload.model_fields_set
                or wants_public
            ),
        )
        if wants_manage and not await self.can_manage(meeting.gremium_id, principal):
            raise ForbiddenError("only a session manager may plan this meeting")
        if wants_write and not await self.can_write(meeting, principal):
            raise ForbiddenError("not allowed to control this meeting")
        # The protokollant leads the room. The session lead may take over or override.
        if wants_now and not await self.can_manage_votes(meeting, principal):
            raise ForbiddenError("not allowed to set the current agenda item")
        if wants_now and meeting.status == "closed":
            raise ConflictError("the session is closed — it has no current agenda item")
        if wants_now and payload.current_agenda_item_id is not None:
            owner = await self.session.scalar(
                select(MeetingAgendaItem.meeting_id).where(
                    MeetingAgendaItem.id == payload.current_agenda_item_id
                )
            )
            if owner != meeting.id:
                raise NotFoundError(
                    f"agenda item {payload.current_agenda_item_id} not found in this meeting"
                )

        # The status runs only forward (F9, O13): planned to live, live to closed. A
        # repeat of the current status is a no-op. ``closed`` is terminal, and a
        # meeting that does not take place is deleted, not closed.
        status_change = payload.status is not None and payload.status != meeting.status
        if status_change and (meeting.status, payload.status) not in _TRANSITIONS:
            raise ConflictError(
                f"a meeting cannot change from {meeting.status} to {payload.status}; "
                "the status runs planned, live, closed",
                code="invalid_status_transition",
            )
        closing = status_change and payload.status == "closed"
        # O12: a meeting with an open vote does not close. The lead closes or cancels
        # the vote first.
        if closing and await self.open_vote(meeting.id) is not None:
            raise ConflictError(
                "a vote of this meeting is still open — close or cancel it first",
                code="open_vote",
            )

        # A closed meeting is frozen: date, time and protokollant stay immutable,
        # because the protocol refers to this planning data.
        if meeting.status == "closed" and wants_manage:
            raise ConflictError("the session is closed — its settings can no longer be changed")

        before = _snapshot(meeting)
        now = datetime.now(UTC)
        guest_events = (
            await self._apply_public(meeting, payload, principal, now) if wants_public else None
        )
        # planned to live: the router creates the protocol at meeting start, after this
        # commit, and nobody takes minutes or votes before that. ``meeting.status`` is
        # set only AFTER the protokollant check, which keeps the change atomic: no
        # ``live`` without a protokollant, not even in memory on a rejected patch.
        going_live = status_change and payload.status == "live"
        # A handover writes its own audit entry (``protokollant_handover``), so the
        # ``meeting_update`` entry leaves the protokollant out then.
        handed_over = False
        if payload.active_application_id is not None:
            meeting.active_application_id = payload.active_application_id
        if wants_now:
            old_item = meeting.current_agenda_item_id
            meeting.current_agenda_item_id = payload.current_agenda_item_id
            # Z3: a forward move starts the planned handover in this transaction.
            if meeting.status == "live" and await self.activate_planned(
                meeting, old_item, payload.current_agenda_item_id, principal.sub, now
            ):
                handed_over = True
        if "date" in payload.model_fields_set:
            meeting.date = payload.date
        if "start_time" in payload.model_fields_set:
            meeting.start_time = payload.start_time
        if "end_time" in payload.model_fields_set:
            meeting.end_time = payload.end_time
        # The end time must be after the start time. The schema checks this only on
        # create. The service checks it only on a patch that touches a time, so a
        # pure status or protokollant patch never fails here.
        if (
            ("start_time" in payload.model_fields_set or "end_time" in payload.model_fields_set)
            and meeting.start_time is not None
            and meeting.end_time is not None
            and meeting.end_time <= meeting.start_time
        ):
            raise BadRequestError("endTime must be after startTime")
        # The same protokollant again is a no-op, so the settings dialog can send the
        # value with every save. It skips the O20 check of a new assignment too.
        if (
            "protokollant_id" in payload.model_fields_set
            and payload.protokollant_id != meeting.protokollant_id
        ):
            # After the finalization the protokollant is part of the signed
            # document, so the assignment is locked.
            if await self._protocol_final(meeting.id):
                raise ConflictError("protocol is finalized — the protokollant can no longer change")
            if meeting.status == "live":
                # Z3: a new protokollant of a live meeting is a handover ``now``. A
                # live meeting always keeps a protokollant.
                if payload.protokollant_id is None:
                    raise ConflictError(
                        "a live meeting needs a protokollant — hand the minutes over instead"
                    )
                previous = meeting.protokollant_id
                await self.check_keeper(meeting.gremium_id, payload.protokollant_id)
                await self.switch_now(meeting, payload.protokollant_id, principal.sub, now)
                await self._audit_handover(
                    meeting,
                    principal.sub,
                    mode="now",
                    previous=previous,
                    target=payload.protokollant_id,
                )
                handed_over = True
            else:
                meeting.protokollant_id = await self._resolve_protokollant(
                    meeting.gremium_id, payload.protokollant_id
                )
        # A meeting needs a protokollant before it goes live. The protokollant
        # writes the protocol that the start creates.
        if going_live and meeting.protokollant_id is None:
            raise ConflictError("assign a protokollant before starting the meeting")
        cancelled: list[Vote] = []
        if going_live and meeting.started_at is None:
            # Z7: the real start, set once. The protocol header and the UI read it.
            meeting.started_at = now
        if going_live:
            # Z3: the first period of the protokollant starts with the meeting.
            await self.open_first_period(meeting, principal.sub, now)
        if closing:
            # Z3: the close ends the running period and drops the planned one.
            await self.close_periods(meeting, now)
            # Set the close timestamp once, on the transition to ``closed``. It
            # fills the "end" line of the protocol title page.
            meeting.closed_at = now
            # A draft of a closed meeting can never open (O12). Local import: the
            # voting service imports the flow engine, which reaches back into this
            # module.
            from app.modules.voting.service import VotingService

            cancelled = await VotingService(self.session).cancel_drafts_for_meeting(
                meeting.id, now=now, actor=principal.sub
            )
            # #17: the requests that never got admitted go, and every guest token.
            await GuestService(self.session).purge_on_close(meeting)
        if payload.status is not None:
            meeting.status = payload.status
        after = _snapshot(meeting)
        if handed_over:
            after["protokollantId"] = before["protokollantId"]
        changes = {
            key: {"from": before[key], "to": after[key]}
            for key in after
            if before[key] != after[key]
        }
        if changes:
            await audit_record(
                self.session,
                actor=principal.sub,
                action=AuditAction.MEETING_UPDATE,
                target_type="meeting",
                target_id=str(meeting.id),
                data={"gremiumId": str(meeting.gremium_id), "changes": changes},
            )
        await self.session.flush()
        cancelled_events = await self._cancelled_events(cancelled)
        await self.session.commit()
        await self._publish_cancelled(cancelled_events)
        if guest_events is not None:
            await GuestService(self.session, self.publisher).publish(meeting.id, guest_events)
        votes = (await self._votes_for([meeting.id], principal)).get(meeting.id, [])
        out = await self._emit(meeting, principal, votes=votes)
        if self.publisher is not None:
            await self.publisher.meeting_state(out)
        return out

    async def _apply_public(
        self, meeting: Meeting, payload: MeetingPatch, principal: Principal, now: datetime
    ) -> GuestEvents | None:
        """Apply ``publicJoin`` and ``guestsMode`` of a patch (#17), without a commit.

        Switching ``guestsMode`` from ``vote`` to ``watch`` is blocked while a vote with
        guests is open: the guests would lose the ballot in the middle of the vote.
        Switching ``publicJoin`` off voids the open requests and removes the admitted
        guests; their cast ballots stay counted. A change writes
        ``meeting_public_join_changed``.

        Returns:
            The guest broadcasts to send after the commit, or None without a change.

        Raises:
            ConflictError: ``guest_vote_open``.
        """
        old_public, old_mode = meeting.public_join, meeting.guests_mode
        new_public = old_public if payload.public_join is None else payload.public_join
        new_mode = old_mode if payload.guests_mode is None else payload.guests_mode
        if (old_public, old_mode) == (new_public, new_mode):
            return None
        if old_mode == "vote" and new_mode == "watch" and await self._guest_vote_open(meeting.id):
            raise ConflictError(
                "A vote with guests is open. Close it before the guests only watch.",
                code="guest_vote_open",
            )
        meeting.public_join = new_public
        meeting.guests_mode = new_mode
        guests = GuestService(self.session)
        events = GuestEvents(counts=True)
        if new_public:
            await guests.ensure_code(meeting)
        elif old_public:
            events = await guests.switch_off(meeting, actor_sub=principal.sub, now=now)
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.MEETING_PUBLIC_JOIN_CHANGED,
            target_type="meeting",
            target_id=str(meeting.id),
            data={
                "gremiumId": str(meeting.gremium_id),
                "publicJoin": {"from": old_public, "to": new_public},
                "guestsMode": {"from": old_mode, "to": new_mode},
            },
        )
        return events

    async def _guest_vote_open(self, meeting_id: UUID) -> bool:
        """Tell if the meeting has an open vote with guests (#17)."""
        found = await self.session.scalar(
            select(Vote.id)
            .where(
                Vote.meeting_id == meeting_id,
                Vote.status == "open",
                Vote.config["guestsVote"].as_boolean().is_(True),
            )
            .limit(1)
        )
        return found is not None

    async def _cancelled_events(self, votes: list[Vote]) -> list[VoteOut]:
        """Read the ``vote_cancelled`` payloads before the commit.

        The method runs before the commit, while each vote still has its
        ``meeting_id``. After a meeting delete the database sets that reference to
        ``NULL``, and a payload read after the commit has no meeting channel.
        """
        if self.publisher is None or not votes:
            return []
        from app.modules.voting.service import VotingService

        voting = VotingService(self.session)
        return [await voting.get(vote.id) for vote in votes]

    async def _publish_cancelled(self, events: list[VoteOut]) -> None:
        """Send ``vote_cancelled`` for the drafts that a close or a delete cancelled.

        The method runs after the commit. A broker fault must not fail the committed
        change, so the method only logs it.
        """
        if self.publisher is None:
            return
        for event in events:
            try:
                await self.publisher.vote_cancelled(event)
            except Exception:  # noqa: BLE001 - the broadcast is best effort
                logger.warning("vote_cancelled broadcast failed (vote=%s)", event.id)

    async def broadcast_state(self, meeting_id: UUID, principal: Principal) -> None:
        """Re-send ``meeting_state`` without a state change.

        A protocol edit or an agenda-item edit calls this, so live followers reload
        the new state.
        """
        meeting = await self._get(meeting_id)
        votes = (await self._votes_for([meeting.id])).get(meeting.id, [])
        out = await self._emit(meeting, principal, votes=votes)
        if self.publisher is not None:
            await self.publisher.meeting_state(out)

    async def _protocol_final(self, meeting_id: UUID) -> bool:
        """Report whether the protocol of the meeting is final."""
        # Local import: ``protocol`` depends on ``livevote``. A module-level import
        # would cycle.
        from app.modules.protocol.models import Protocol

        status = await self.session.scalar(
            select(Protocol.status).where(Protocol.meeting_id == meeting_id)
        )
        return status == "final"

    async def delete(self, meeting_id: UUID, principal: Principal) -> None:
        """Delete a meeting.

        Only a meeting manager (``session.manage``) or an admin may delete a
        meeting. A meeting with a final protocol also needs the global
        ``meeting.delete_finalized`` permission, because the protocol is a signed
        and mailed document. The service audits every delete.

        The delete locks the meeting row, as the close and the vote open do. A
        meeting with an open vote does not delete: the lead closes or cancels the
        vote first. The delete cancels the draft votes of the meeting in the same
        transaction (reason ``meeting_deleted``), then sends ``vote_cancelled``
        after the commit. Thus no vote of a deleted meeting can open later.

        The cascade removes the protocol, the agenda and the attendance. The
        database detaches bound votes with ``SET NULL`` on ``meeting_id`` and on
        ``agenda_item_id`` (F21), so the votes, their ballots and their results
        survive.

        Raises:
            ForbiddenError: The caller does not manage the meeting, or the protocol
                is final and the caller does not hold ``meeting.delete_finalized``.
            ConflictError: The meeting still has an open vote (``open_vote``).
        """
        # The lock serializes the delete with the vote open and the close. Without
        # it, a vote could open between the check below and the delete.
        meeting = await self._get(meeting_id, for_update=True)
        if not await self.can_manage(meeting.gremium_id, principal):
            raise ForbiddenError("not allowed to delete this meeting")
        finalized = await self._protocol_final(meeting_id)
        if finalized and not principal.has("meeting.delete_finalized"):
            raise ForbiddenError(
                "this meeting has a finalized protocol — deleting it requires "
                "the meeting.delete_finalized permission"
            )
        # An open vote of a deleted meeting would stay open without its meeting
        # scope: interim counts, present count and delegation checks all depend on
        # it.
        if await self.open_vote(meeting.id) is not None:
            raise ConflictError(
                "a vote of this meeting is still open — close or cancel it first",
                code="open_vote",
            )
        # Local import: the voting service imports the flow engine, which reaches
        # back into this module.
        from app.modules.voting.service import VotingService

        cancelled = await VotingService(self.session).cancel_drafts_for_meeting(
            meeting.id, now=datetime.now(UTC), actor=principal.sub, reason="meeting_deleted"
        )
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.MEETING_DELETE,
            target_type="meeting",
            target_id=str(meeting.id),
            data={
                "title": meeting.title,
                "gremiumId": str(meeting.gremium_id),
                "finalizedProtocol": finalized,
            },
        )
        cancelled_events = await self._cancelled_events(cancelled)
        await self.session.delete(meeting)
        await self.session.commit()
        await self._publish_cancelled(cancelled_events)

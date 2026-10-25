"""Meeting lifecycle: create, patch (planned to live to closed), broadcast, delete.

The status runs only forward: ``planned`` to ``live`` to ``closed``. A
repeat of the current status is a no-op. Every other change gives 409
``invalid_status_transition``. A meeting that does not take place is deleted, not
closed.

The lifecycle also drives the periods of the protocol keeper (see
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
from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.guests import GuestEvents, GuestService
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.livevote.open_window import check_open
from app.modules.livevote.schemas import MeetingCreate, MeetingOut, MeetingPatch
from app.modules.livevote.service.handover import HandoverOps
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteOut
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationProblem,
)

logger = logging.getLogger(__name__)

#: The only status changes of a meeting. A repeat of the current status is a
#: no-op and not in this set.
_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {("planned", "live"), ("live", "closed")}
)

#: The planning fields that MEETING_UPDATE records, as (model attribute, JSON key).
_AUDITED_FIELDS: tuple[tuple[str, str], ...] = (
    ("status", "status"),
    ("title", "title"),
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

        A public meeting gets its join link at once, so the link can go into the invitation.
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
            await self._assert_public_join_allowed(payload.gremium_id)
        self.session.add(meeting)
        await self.session.flush()
        if payload.public_join:
            await GuestService(self.session).ensure_code(meeting)
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
        """Validate the protokollant: an active member with ``protocol.write``.

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
        (protokollant or manager). Title, date, time and the protokollant assignment
        need ``canManage`` (meeting manager). The title can change while the meeting
        is ``planned`` or ``live``. A closed meeting keeps its title, because the
        protocol that goes out names the meeting.

        The start (``planned`` to ``live``) sets ``started_at`` once. The close (``live``
        to ``closed``) sets ``closed_at`` and cancels the draft votes of the meeting in
        the same transaction, then sends ``vote_cancelled`` after the commit. A status
        change or a planning change writes ``meeting_update``.

        ``completeAgendaItemId`` sets the done mark of the item that the room leaves,
        in the same transaction as the move ("Nächster TOP"). It needs the gate of the
        done mark (``can_mark_done``, 403) and an item of this meeting (404).

        The start opens the first keeper period, and the close ends the running
        one. A forward move of the current agenda item starts a planned handover. A
        new protokollant of a live meeting is a handover ``now``. Each handover writes
        ``protokollant_handover`` instead of a protokollant change in
        ``meeting_update``. The same protokollant again is a no-op. A new
        protokollant needs ``protocol.write`` in the gremium (422).

        Public participation and the guest mode are planning values of the lead. A status
        change locks the meeting row. The open of a vote takes the same lock, so the
        open-vote check and the close cannot race. A move of the agenda item and a
        protokollant change can change the keeper periods, so they take the lock too, as the
        handover route does.

        The current agenda item follows the protokollant and nobody else, so a look of the
        session lead at another item does not move the beamer and the followers. The lead
        takes the minutes over first (handover) to move it.

        The status runs only forward. A repeat of the current status is a no-op. ``closed``
        is terminal, and a meeting that does not take place is deleted, not closed. A closed
        meeting is frozen, because the protocol refers to its planning data. The open window
        reads the stored planning before this patch changes it, so a date change in the same
        patch cannot move the window.

        On the start the router creates the protocol after this commit, and nobody takes
        minutes or votes before that. ``meeting.status`` changes only after the protokollant
        check, which keeps the change atomic: no ``live`` without a protokollant, not even
        in memory on a rejected patch. A meeting needs a protokollant before it goes live,
        because the protokollant writes the protocol that the start creates.

        The schema checks the order of the start and end time only on create. The service
        checks it only on a patch that touches a time, so a pure status or protokollant
        patch never fails on it. The same protokollant again is a no-op, so the settings
        dialog can send the value with every save; it also skips the ``protocol.write``
        check of a new assignment. After the finalization the protokollant is part of the
        signed document, so the assignment is locked. A live meeting always keeps a
        protokollant.

        The close drops the planned keeper period, cancels the drafts, which can never open,
        and removes the requests that never got admitted, the guest names and every guest
        token. The voting service is imported locally, because it imports the flow engine,
        which reaches back into this module.

        Raises:
            ConflictError: The status change is not ``planned`` to ``live`` or ``live``
                to ``closed`` (``invalid_status_transition``), the meeting still has an
                open vote on close (``open_vote``), the start has no protokollant, the
                start is before the open window (``meeting_too_early``) or early and not
                confirmed (``early_open_unconfirmed``), or the meeting is closed and
                the patch changes its planning.
        """
        wants_public = payload.public_join is not None or payload.guests_mode is not None
        wants_manage = (
            "title" in payload.model_fields_set
            or "date" in payload.model_fields_set
            or "start_time" in payload.model_fields_set
            or "end_time" in payload.model_fields_set
            or "protokollant_id" in payload.model_fields_set
            or wants_public
        )
        wants_write = payload.status is not None or payload.active_application_id is not None
        wants_now = "current_agenda_item_id" in payload.model_fields_set
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
        if wants_now and not await self.can_set_current_item(meeting, principal):
            raise ForbiddenError("only the protokollant may set the current agenda item")
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
        if payload.complete_agenda_item_id is not None and not await self.can_mark_done(
            meeting, principal
        ):
            raise ForbiddenError("not allowed to mark this agenda item as done")

        status_change = payload.status is not None and payload.status != meeting.status
        if status_change and (meeting.status, payload.status) not in _TRANSITIONS:
            raise ConflictError(
                f"a meeting cannot change from {meeting.status} to {payload.status}; "
                "the status runs planned, live, closed",
                code="invalid_status_transition",
            )
        closing = status_change and payload.status == "closed"
        if closing and await self.open_vote(meeting.id) is not None:
            raise ConflictError(
                "a vote of this meeting is still open — close or cancel it first",
                code="open_vote",
            )

        if meeting.status == "closed" and wants_manage:
            raise ConflictError("the session is closed — its settings can no longer be changed")

        before = _snapshot(meeting)
        now = datetime.now(UTC)
        if status_change and payload.status == "live":
            window = (await self._open_windows([meeting]))[meeting.id]
            check_open(window, now=now, confirmed=payload.confirm_early)
        guest_events = (
            await self._apply_public(meeting, payload, principal, now) if wants_public else None
        )
        going_live = status_change and payload.status == "live"
        handed_over = False
        if payload.active_application_id is not None:
            meeting.active_application_id = payload.active_application_id
        if wants_now:
            old_item = meeting.current_agenda_item_id
            meeting.current_agenda_item_id = payload.current_agenda_item_id
            if meeting.status == "live" and await self.activate_planned(
                meeting, old_item, payload.current_agenda_item_id, principal.sub, now
            ):
                handed_over = True
        if payload.complete_agenda_item_id is not None:
            await AgendaService(self.session).set_done_in_tx(
                meeting,
                payload.complete_agenda_item_id,
                done=True,
                actor=principal.sub,
                via="next",
            )
        if payload.title is not None:
            meeting.title = payload.title
        if "date" in payload.model_fields_set:
            meeting.date = payload.date
        if "start_time" in payload.model_fields_set:
            meeting.start_time = payload.start_time
        if "end_time" in payload.model_fields_set:
            meeting.end_time = payload.end_time
        if (
            ("start_time" in payload.model_fields_set or "end_time" in payload.model_fields_set)
            and meeting.start_time is not None
            and meeting.end_time is not None
            and meeting.end_time <= meeting.start_time
        ):
            raise BadRequestError("endTime must be after startTime")
        if (
            "protokollant_id" in payload.model_fields_set
            and payload.protokollant_id != meeting.protokollant_id
        ):
            if await self._protocol_final(meeting.id):
                raise ConflictError("protocol is finalized — the protokollant can no longer change")
            if meeting.status == "live":
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
        if going_live and meeting.protokollant_id is None:
            raise ConflictError("assign a protokollant before starting the meeting")
        cancelled: list[Vote] = []
        if going_live and meeting.started_at is None:
            meeting.started_at = now
        if going_live:
            await self.open_first_period(meeting, principal.sub, now)
        if closing:
            await self.close_periods(meeting, now)
            meeting.closed_at = now
            from app.modules.voting.service import VotingService

            cancelled = await VotingService(self.session).cancel_drafts_for_meeting(
                meeting.id, now=now, actor=principal.sub
            )
            closed_events = await GuestService(self.session).purge_on_close(meeting)
            if guest_events is not None:
                closed_events.updated[:0] = guest_events.updated
            guest_events = closed_events
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
        """Apply ``publicJoin`` and ``guestsMode`` of a patch, without a commit.

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
        if new_public and not old_public:
            await self._assert_public_join_allowed(meeting.gremium_id)
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

    async def _assert_public_join_allowed(self, gremium_id: UUID) -> None:
        """Allow public participation only in a gremium without a quorum.

        A gremium with a quorum (StuPa, AStA) decides by the members only; the feature
        serves the gremien without a quorum (Fachschaften).

        Raises:
            ValidationProblem: ``public_join_needs_no_quorum``.
        """
        if await self.gremium_has_quorum(gremium_id):
            raise ValidationProblem(
                "Public participation needs a gremium without a quorum.",
                code="public_join_needs_no_quorum",
                errors=[{"field": "publicJoin", "msg": "the gremium has a quorum"}],
            )

    async def gremium_has_quorum(self, gremium_id: UUID) -> bool:
        """Tell if the gremium sets a default quorum (the vote config of its meetings)."""
        from app.modules.admin.models import Gremium

        percent = await self.session.scalar(
            select(Gremium.quorum_percent).where(Gremium.id == gremium_id)
        )
        return percent is not None

    async def _guest_vote_open(self, meeting_id: UUID) -> bool:
        """Tell if the meeting has an open vote with guests."""
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

        The meeting close calls it before the commit, so the payloads and the
        commit see the same state.
        """
        if self.publisher is None or not votes:
            return []
        from app.modules.voting.service import VotingService

        voting = VotingService(self.session)
        return [await voting.get(vote.id) for vote in votes]

    async def _publish_cancelled(self, events: list[VoteOut]) -> None:
        """Send ``vote_cancelled`` for the drafts that a close cancelled.

        The method runs after the commit. A broker fault must not fail the committed
        change, so the method only logs it.

        A failed broadcast does not fail the close, because the broadcast is best effort.
        """
        if self.publisher is None:
            return
        for event in events:
            try:
                await self.publisher.vote_cancelled(event)
            except Exception:
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
        """Report whether the protocol of the meeting is final.

        The protocol model is imported locally, because ``protocol`` depends on ``livevote``
        and a module-level import would cycle.
        """
        from app.modules.protocol.models import Protocol

        status = await self.session.scalar(
            select(Protocol.status).where(Protocol.meeting_id == meeting_id)
        )
        return status == "final"

    async def delete(self, meeting_id: UUID, principal: Principal) -> None:
        """Delete a meeting.

        Only a meeting manager (``session.manage``) or an admin may delete a
        meeting. The delete locks the meeting row, as the close and the vote open
        do, and then applies the rules of ``delete_locked``. The service audits
        every delete.

        The row lock serializes the delete with the vote open and the close. Without it, a
        vote could open between the check and the delete.

        Raises:
            ForbiddenError: The caller does not manage the meeting, or the protocol
                is final and the caller does not hold ``meeting.delete_finalized``
                (``meeting_finalized``).
            ConflictError: The meeting still has an open vote (``open_vote``).
        """
        meeting = await self._get(meeting_id, for_update=True)
        if not await self.can_manage(meeting.gremium_id, principal):
            raise ForbiddenError("not allowed to delete this meeting")
        await self.delete_locked(meeting, principal)
        await self.session.commit()

    async def delete_locked(self, meeting: Meeting, principal: Principal) -> None:
        """Delete a meeting that the caller locked, without a commit.

        The caller locks the meeting row (``SELECT … FOR UPDATE``) and checks the
        right to manage the meeting. This method applies the rules of
        ``check_deletable``, deletes every vote of the meeting in the same
        transaction, in any status (draft, cancelled, closed, secret, with guests),
        together with their ballots, secret ballots, voted markers and protocol
        references (``VotingService.delete_for_meeting``, one ``vote_delete`` per
        vote with the reason ``meeting_deleted``), and then deletes the meeting
        (``write_delete``). An application that such a vote decided keeps its
        status; its timeline shows the vote as deleted.

        The voting service is imported locally, because it imports the flow engine, which
        reaches back into this module.

        Raises:
            ForbiddenError: The protocol is final and the caller does not hold
                ``meeting.delete_finalized`` (``meeting_finalized``).
            ConflictError: The meeting still has an open vote (``open_vote``).
        """
        finalized = await self.check_deletable(meeting, principal)
        from app.modules.voting.service import VotingService

        deleted_votes = await VotingService(self.session).delete_for_meeting(
            meeting.id, actor=principal.sub
        )
        await self.write_delete(
            meeting, principal, finalized=finalized, deleted_votes=deleted_votes
        )

    async def check_deletable(self, meeting: Meeting, principal: Principal) -> bool:
        """Apply the refusal rules that every meeting delete shares, without a write.

        A meeting with a final protocol needs the global ``meeting.delete_finalized``
        permission, because the protocol is a signed and mailed document. A meeting
        with an open vote does not delete: the lead closes or cancels the vote
        first. The Gremium delete runs this check for all its meetings before its
        first write.

        An open vote of a deleted meeting would stay open without its meeting scope, and the
        interim counts, the present count and the delegation checks all depend on that
        scope.

        Returns:
            True when the protocol of the meeting is final.

        Raises:
            ForbiddenError: The protocol is final and the caller does not hold
                ``meeting.delete_finalized`` (``meeting_finalized``).
            ConflictError: The meeting still has an open vote (``open_vote``).
        """
        finalized = await self._protocol_final(meeting.id)
        if finalized and not principal.has("meeting.delete_finalized"):
            raise ForbiddenError(
                "this meeting has a finalized protocol — deleting it requires "
                "the meeting.delete_finalized permission",
                code="meeting_finalized",
            )
        if await self.open_vote(meeting.id) is not None:
            raise ConflictError(
                "a vote of this meeting is still open — close or cancel it first",
                code="open_vote",
            )
        return finalized

    async def write_delete(
        self,
        meeting: Meeting,
        principal: Principal,
        *,
        finalized: bool,
        deleted_votes: list[UUID],
        reason: str | None = None,
    ) -> None:
        """Audit and delete a meeting whose votes are gone, without a commit.

        ``meeting_delete`` carries the number and the ids of the deleted votes,
        never a choice or a name, and ``reason`` when another delete caused this
        one (``gremium_deleted``). The cascade then removes the protocol, the
        agenda, the attendance, the guests and the delegations.

        The session flushes at once, because a Gremium delete that follows must not cascade
        over a meeting row that the session still has to delete.
        """
        data: dict[str, Any] = {
            "title": meeting.title,
            "gremiumId": str(meeting.gremium_id),
            "finalizedProtocol": finalized,
            "deletedVotes": len(deleted_votes),
            "deletedVoteIds": [str(vote_id) for vote_id in deleted_votes],
        }
        if reason is not None:
            data["reason"] = reason
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.MEETING_DELETE,
            target_type="meeting",
            target_id=str(meeting.id),
            data=data,
        )
        await self.session.delete(meeting)
        await self.session.flush()

"""Agenda service that binds applications to a meeting.

An application is assignable when the Gremium of the meeting decides its current
vote state: `application.vote_gremium_id`, the snapshot that the flow engine sets on
entry into a vote state, is the Gremium of the meeting.
The agenda keeps an explicit order (`position`). It is the source of the agenda
items in the protocol.

State rules:

* Add, reorder, rename and remove need a `planned` or `live` meeting. A closed
  meeting gives 409 `meeting_closed`.
* Remove gives 409 `agenda_item_has_vote` while the item has an open or closed vote.
  It deletes the draft and cancelled votes of the item first, each with a
  `vote_delete` audit entry. To delete these votes the caller needs the
  `canManageVotes` right, else 403.
* Add and remove lock the meeting row, as the meeting close and the vote open do.
* The Markdown body and the `nonPublic` flag are open from the planning until the
  protocol leaves the draft. The minute-taker can thus write the minutes of an item
  before the meeting starts.

The done mark of an item ("TOP abhaken") follows the minutes window too. A person
sets and removes it by hand, and the move to the next item sets it for the item that
the room leaves.

Every change writes an audit entry: `agenda_item_add`, `agenda_item_update`,
`agenda_item_remove`, `agenda_reorder`, `agenda_item_done` and
`agenda_item_reopened`. A body edit of a planned or live meeting
is the preparation or the running minutes, and its autosave is not audited. A body
edit after the close is a correction of the minutes and is audited, without the text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.flow.models import State
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.livevote.schemas import AgendaItemOut, AssignableApplicationOut
from app.modules.protocol.models import Protocol
from app.shared.errors import ConflictError, NotFoundError

#: The meeting states that accept a change of the agenda.
_AGENDA_OPEN = frozenset({"planned", "live"})


def title_of(data: dict[str, Any] | None) -> str | None:
    """Return the application title from the system field `title`, or `None`."""
    if not data:
        return None
    value = data.get("title")
    return value.strip() if isinstance(value, str) and value.strip() else None


def agenda_order() -> tuple[ColumnElement[Any], ...]:
    """Return the sort keys of the agenda order.

    `position` orders the items. The creation time and the id break a tie, so the
    agenda list and the numbers in `MeetingOut` always agree.
    """
    return (
        MeetingAgendaItem.position.asc(),
        MeetingAgendaItem.created_at.asc(),
        MeetingAgendaItem.id.asc(),
    )


class AgendaService:
    """Manage the agenda of a meeting: assign, remove and list applications."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a session."""
        self.session = session

    async def _meeting(self, meeting_id: UUID, *, for_update: bool = False) -> Meeting:
        """Load a meeting by id.

        ``for_update`` locks the meeting row until the commit and reads the current
        values again. The meeting close and the vote open take the same lock, so an
        add or a remove cannot race them.

        Raises:
            NotFoundError: No meeting has this id.
        """
        stmt = select(Meeting).where(Meeting.id == meeting_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        meeting = (await self.session.execute(stmt)).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    @staticmethod
    def _assert_agenda_open(meeting: Meeting) -> None:
        """Refuse a change of the agenda structure after the close.

        Raises:
            ConflictError: The meeting is closed (``meeting_closed``).
        """
        if meeting.status not in _AGENDA_OPEN:
            raise ConflictError(
                "the meeting is closed — its agenda can no longer change",
                code="meeting_closed",
            )

    async def _assert_minutes_open(self, meeting: Meeting) -> None:
        """Refuse a body or ``nonPublic`` edit outside the minutes window.

        The window is a ``planned`` or ``live`` meeting, or a closed meeting whose
        protocol is still a draft. A ``planned`` meeting has no protocol yet, but the
        text of its items is already the start of the minutes.

        Raises:
            ConflictError: The protocol is no longer a draft (``protocol_locked``).
        """
        if meeting.status == "closed":
            status = await self.session.scalar(
                select(Protocol.status).where(Protocol.meeting_id == meeting.id)
            )
            if status != "draft":
                raise ConflictError(
                    "the protocol is no longer a draft — the minutes can no longer change",
                    code="protocol_locked",
                )

    async def _audit(
        self,
        action: AuditAction,
        *,
        actor: str | None,
        item: MeetingAgendaItem,
        **extra: Any,
    ) -> None:
        """Write one agenda audit entry with id references only, never a text."""
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type="meeting",
            target_id=str(item.meeting_id),
            data={
                "agendaItemId": str(item.id),
                "applicationId": str(item.application_id) if item.application_id else None,
                **extra,
            },
        )

    async def _state_labels(self, state_ids: set[UUID]) -> dict[UUID, dict]:
        """Return the label of each state, for the assignable list."""
        if not state_ids:
            return {}
        rows = await self.session.execute(
            select(State.id, State.label_i18n).where(State.id.in_(state_ids))
        )
        return {sid: label for sid, label in rows.all()}

    async def item(self, meeting_id: UUID, item_id: UUID) -> MeetingAgendaItem:
        """Load one agenda item of the meeting.

        Raises:
            NotFoundError: The meeting has no agenda item with this id.
        """
        row = (
            await self.session.execute(
                select(MeetingAgendaItem).where(
                    MeetingAgendaItem.meeting_id == meeting_id,
                    MeetingAgendaItem.id == item_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"agenda item {item_id} not found")
        return row

    async def list(self, meeting_id: UUID) -> list[AgendaItemOut]:
        """List the agenda items of a meeting in their order.

        A free-text item has no application and carries its own title.
        """
        await self._meeting(meeting_id)
        rows = (
            await self.session.scalars(
                select(MeetingAgendaItem)
                .where(MeetingAgendaItem.meeting_id == meeting_id)
                .order_by(*agenda_order())
            )
        ).all()
        if not rows:
            return []
        app_ids = [r.application_id for r in rows if r.application_id is not None]
        apps = {
            a.id: a
            for a in (
                await self.session.scalars(
                    select(Application).where(Application.id.in_(app_ids))
                )
            ).all()
        }
        state_ids = {a.current_state_id for a in apps.values() if a.current_state_id}
        states = (
            {
                s.id: s
                for s in (
                    await self.session.scalars(
                        select(State).where(State.id.in_(state_ids))
                    )
                ).all()
            }
            if state_ids
            else {}
        )
        out: list[AgendaItemOut] = []
        for r in rows:
            app = apps.get(r.application_id) if r.application_id is not None else None
            state = (
                states.get(app.current_state_id)
                if app is not None and app.current_state_id is not None
                else None
            )
            title = title_of(app.data) if app is not None else r.title
            out.append(
                AgendaItemOut(
                    id=r.id,
                    applicationId=r.application_id,
                    todoId=r.todo_id,
                    title=title,
                    body=r.body,
                    position=r.position,
                    nonPublic=r.non_public,
                    doneAt=r.done_at,
                    stateLabel=state.label_i18n if state is not None else None,
                    amount=app.amount if app is not None else None,
                )
            )
        return out

    async def set_body(
        self,
        meeting_id: UUID,
        item_id: UUID,
        body: str | None = None,
        title: str | None = None,
        non_public: bool | None = None,
        *,
        actor: str | None = None,
    ) -> list[AgendaItemOut]:
        """Update the Markdown body, the title or the visibility of an agenda item.

        A `title` renames a free-text item only. An application item keeps the
        title of its application. `non_public` hides the item content in the
        public protocol PDF.

        A rename needs a `planned` or `live` meeting. The body and `non_public`
        need a `planned` or `live` meeting, or a closed meeting with a draft protocol.
        A change writes `agenda_item_update` with the changed field names. The body
        counts only after the close.

        The live minutes autosave every second, so only a correction after the close goes
        into the audit log. An item that guests saw and voted on cannot become non-public
        afterwards, or the guest view would have shown non-public content.

        Raises:
            NotFoundError: The meeting has no agenda item with this id.
            ConflictError: The meeting state does not allow the change.
        """
        meeting = await self._meeting(meeting_id)
        row = await self.item(meeting_id, item_id)
        renames = title is not None and row.application_id is None
        if renames:
            self._assert_agenda_open(meeting)
        if body is not None or non_public is not None:
            await self._assert_minutes_open(meeting)
        changed: list[str] = []
        if body is not None and body != row.body:
            row.body = body
            if meeting.status == "closed":
                changed.append("body")
        if renames and title is not None and title.strip() != row.title:
            row.title = title.strip()
            changed.append("title")
        if non_public is not None and non_public != row.non_public:
            if non_public and await self._has_guest_vote(row.id):
                raise ConflictError(
                    "Guests voted on this agenda item; it cannot become non-public.",
                    code="guests_vote_on_item",
                )
            row.non_public = non_public
            changed.append("nonPublic")
        if changed:
            await self._audit(
                AuditAction.AGENDA_ITEM_UPDATE, actor=actor, item=row, fields=changed
            )
        await self.session.flush()
        await self.session.commit()
        return await self.list(meeting_id)

    async def set_done(
        self, meeting_id: UUID, item_id: UUID, *, done: bool, actor: str
    ) -> list[AgendaItemOut]:
        """Set or remove the done mark of an agenda item, then commit.

        The rules are those of `set_done_in_tx`. The caller checks the right.

        Raises:
            NotFoundError: The meeting has no agenda item with this id.
            ConflictError: The protocol is no longer a draft (``protocol_locked``).
        """
        meeting = await self._meeting(meeting_id)
        await self.set_done_in_tx(meeting, item_id, done=done, actor=actor)
        await self.session.commit()
        return await self.list(meeting_id)

    async def set_done_in_tx(
        self,
        meeting: Meeting,
        item_id: UUID,
        *,
        done: bool,
        actor: str,
        via: str | None = None,
    ) -> None:
        """Set or remove the done mark of an agenda item. It does not commit.

        The mark follows the minutes window: a `planned` or `live` meeting, or a
        closed meeting with a draft protocol. A mark that does not change writes
        nothing, so a second tick keeps the time and the person of the first one. A
        change writes `agenda_item_done` or `agenda_item_reopened`. `via` names the
        path in the audit entry (`next` for the move to the next item).

        Raises:
            NotFoundError: The meeting has no agenda item with this id.
            ConflictError: The protocol is no longer a draft (``protocol_locked``).
        """
        row = await self.item(meeting.id, item_id)
        await self._assert_minutes_open(meeting)
        if done == (row.done_at is not None):
            return
        if done:
            row.done_at = datetime.now(UTC)
            row.done_by = actor
            action = AuditAction.AGENDA_ITEM_DONE
        else:
            row.done_at = None
            row.done_by = None
            action = AuditAction.AGENDA_ITEM_REOPENED
        extra = {"via": via} if via is not None else {}
        await self._audit(action, actor=actor, item=row, **extra)
        await self.session.flush()

    async def _has_guest_vote(self, item_id: UUID) -> bool:
        """Tell if the item has an open or closed vote with guests."""
        from app.modules.voting.models import Vote

        found = await self.session.scalar(
            select(Vote.id)
            .where(
                Vote.agenda_item_id == item_id,
                Vote.status.in_(("open", "closed")),
                Vote.config["guestsVote"].as_boolean().is_(True),
            )
            .limit(1)
        )
        return found is not None

    async def reorder(
        self, meeting_id: UUID, item_ids: list[UUID], *, actor: str | None = None
    ) -> list[AgendaItemOut]:
        """Set the agenda order to the given sequence of item ids.

        The method skips an id that does not belong to this meeting. It writes
        `agenda_reorder` with the new order of the item ids.

        Raises:
            NotFoundError: The meeting does not exist.
            ConflictError: The meeting is closed.
        """
        meeting = await self._meeting(meeting_id)
        self._assert_agenda_open(meeting)
        rows = {
            r.id: r
            for r in (
                await self.session.scalars(
                    select(MeetingAgendaItem).where(
                        MeetingAgendaItem.meeting_id == meeting_id
                    )
                )
            ).all()
        }
        position = 0
        ordered: list[str] = []
        for item_id in item_ids:
            row = rows.get(item_id)
            if row is not None:
                row.position = position
                position += 1
                ordered.append(str(row.id))
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.AGENDA_REORDER,
            target_type="meeting",
            target_id=str(meeting_id),
            data={"itemIds": ordered},
        )
        await self.session.flush()
        await self.session.commit()
        return await self.list(meeting_id)

    async def assignable(self, meeting_id: UUID) -> list[AssignableApplicationOut]:
        """List the applications of the Gremium in a vote state that are not on the agenda."""
        meeting = await self._meeting(meeting_id)
        existing = set(
            (
                await self.session.scalars(
                    select(MeetingAgendaItem.application_id).where(
                        MeetingAgendaItem.meeting_id == meeting_id
                    )
                )
            ).all()
        )
        apps = (
            await self.session.scalars(
                select(Application)
                .where(Application.vote_gremium_id == meeting.gremium_id)
                .order_by(Application.created_at.desc())
            )
        ).all()
        labels = await self._state_labels(
            {a.current_state_id for a in apps if a.current_state_id is not None}
        )
        out: list[AssignableApplicationOut] = []
        for app in apps:
            if app.id in existing:
                continue
            out.append(
                AssignableApplicationOut(
                    applicationId=app.id,
                    title=title_of(app.data),
                    stateLabel=(
                        labels.get(app.current_state_id)
                        if app.current_state_id is not None
                        else None
                    ),
                )
            )
        return out

    async def _next_position(self, meeting_id: UUID) -> int:
        max_pos = (
            await self.session.execute(
                select(func.max(MeetingAgendaItem.position)).where(
                    MeetingAgendaItem.meeting_id == meeting_id
                )
            )
        ).scalar_one_or_none()
        return (max_pos + 1) if max_pos is not None else 0

    async def add(
        self,
        meeting_id: UUID,
        application_id: UUID | None = None,
        title: str | None = None,
        non_public: bool = False,
        *,
        actor: str | None = None,
    ) -> list[AgendaItemOut]:
        """Add an agenda item for an application or for free text, then commit.

        The rules are those of `add_in_tx`. The method commits only when it added
        an item.

        Raises:
            NotFoundError: The application does not exist.
            ConflictError: The meeting is closed, or the application is not in a
                vote state of the Gremium.
        """
        if await self.add_in_tx(
            meeting_id,
            application_id=application_id,
            title=title,
            non_public=non_public,
            actor=actor,
        ):
            await self.session.commit()
        return await self.list(meeting_id)

    async def add_in_tx(
        self,
        meeting_id: UUID,
        application_id: UUID | None = None,
        title: str | None = None,
        non_public: bool = False,
        *,
        actor: str | None = None,
    ) -> bool:
        """Add an agenda item in the transaction of the caller. It does not commit.

        A `title` creates a free-text item. The method then ignores
        `application_id`. Without a title the application must be in a vote
        state of the Gremium of the meeting. A second add for the same
        application changes nothing. The flow engine calls this method before its
        own commit, so the state change and the new item stay atomic. A new item
        writes `agenda_item_add`. A missing `actor` marks a system add.

        The read uses `populate_existing`, because the flow engine moved the state with a
        bulk UPDATE in this transaction. The current state must come from the database.

        Returns:
            `True` when the method added an item, `False` when the application
            was already on the agenda.

        Raises:
            NotFoundError: The meeting or the application does not exist.
            ConflictError: The meeting is closed, or the application is not in
                a vote state of the Gremium.
        """
        meeting = await self._meeting(meeting_id, for_update=True)
        self._assert_agenda_open(meeting)
        if title is not None:
            item = MeetingAgendaItem(
                meeting_id=meeting_id,
                application_id=None,
                title=title.strip(),
                position=await self._next_position(meeting_id),
                non_public=non_public,
            )
            self.session.add(item)
            await self.session.flush()
            await self._audit(
                AuditAction.AGENDA_ITEM_ADD, actor=actor, item=item, nonPublic=non_public
            )
            return True

        app = await self.session.get(
            Application, application_id, populate_existing=True
        )
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        if app.vote_gremium_id is None or app.vote_gremium_id != meeting.gremium_id:
            raise ConflictError(
                "application is not in a voting state for this committee"
            )
        existing = (
            await self.session.execute(
                select(MeetingAgendaItem.id).where(
                    MeetingAgendaItem.meeting_id == meeting_id,
                    MeetingAgendaItem.application_id == application_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False
        item = MeetingAgendaItem(
            meeting_id=meeting_id,
            application_id=application_id,
            position=await self._next_position(meeting_id),
            non_public=non_public,
        )
        self.session.add(item)
        await self.session.flush()
        await self._audit(
            AuditAction.AGENDA_ITEM_ADD, actor=actor, item=item, nonPublic=non_public
        )
        return True

    async def add_todo_in_tx(
        self,
        meeting_id: UUID,
        *,
        todo_id: UUID,
        title: str,
        non_public: bool = False,
        actor: str | None = None,
    ) -> MeetingAgendaItem:
        """Add an agenda item for a to-do card in the transaction of the caller.

        The item has no application; its ``title`` is the card title and its
        ``todo_id`` the card. The caller checks the card and links it to the item. A
        new item writes ``agenda_item_add``.

        Raises:
            NotFoundError: The meeting does not exist.
            ConflictError: The meeting is closed (``meeting_closed``), or the card is
                already on the agenda (``todo_already_on_agenda``).
        """
        meeting = await self._meeting(meeting_id, for_update=True)
        self._assert_agenda_open(meeting)
        existing = await self.session.scalar(
            select(MeetingAgendaItem.id).where(
                MeetingAgendaItem.meeting_id == meeting_id,
                MeetingAgendaItem.todo_id == todo_id,
            )
        )
        if existing is not None:
            raise ConflictError(
                "the to-do is already on the agenda of this meeting",
                code="todo_already_on_agenda",
            )
        item = MeetingAgendaItem(
            meeting_id=meeting_id,
            application_id=None,
            todo_id=todo_id,
            title=title.strip() or title,
            position=await self._next_position(meeting_id),
            non_public=non_public,
        )
        self.session.add(item)
        await self.session.flush()
        await self._audit(
            AuditAction.AGENDA_ITEM_ADD,
            actor=actor,
            item=item,
            nonPublic=non_public,
            todoId=str(todo_id),
        )
        return item

    async def remove(
        self,
        meeting_id: UUID,
        item_id: UUID,
        *,
        actor: str,
        may_delete_votes: bool,
    ) -> list[AgendaItemOut]:
        """Remove an agenda item.

        The meeting must be `planned` or `live`. An open or closed vote of the item
        blocks the remove. The draft and cancelled votes of the item are deleted
        first, each with `vote_delete`. To delete them, the caller must be allowed to
        delete a vote of the meeting (`may_delete_votes`, the `canManageVotes` gate of
        `DELETE /meetings/{id}/votes/{voteId}`). The remove writes
        `agenda_item_remove`. An unknown item id changes nothing, as before.

        The method locks the meeting row first. The vote open takes the same lock, so
        no vote can open on the item while the remove runs.

        The voting service is imported locally, because it imports the flow engine, and the
        flow engine imports this module.

        Raises:
            NotFoundError: The meeting does not exist.
            ConflictError: The meeting is closed (``meeting_closed``), or the item has
                an open or closed vote (``agenda_item_has_vote``).
            ForbiddenError: The item has a draft or cancelled vote and
                `may_delete_votes` is false.
        """
        from app.modules.voting.service import VotingService

        meeting = await self._meeting(meeting_id, for_update=True)
        self._assert_agenda_open(meeting)
        row = (
            await self.session.execute(
                select(MeetingAgendaItem).where(
                    MeetingAgendaItem.meeting_id == meeting_id,
                    MeetingAgendaItem.id == item_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            deleted = await VotingService(self.session).delete_for_agenda_item(
                row.id, actor=actor, may_delete=may_delete_votes
            )
            await self._audit(
                AuditAction.AGENDA_ITEM_REMOVE,
                actor=actor,
                item=row,
                deletedVoteIds=[str(v) for v in deleted],
            )
            await self.session.delete(row)
            await self.session.commit()
        return await self.list(meeting_id)

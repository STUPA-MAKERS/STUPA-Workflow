"""Agenda service that binds applications to a meeting.

An application is assignable when its current state is a vote state
(`kind=='vote'`) and `config.gremiumId` points at the Gremium of the meeting.
The agenda keeps an explicit order (`position`). It is the source of the agenda
items in the protocol.

State rules (F24, O22, O25):

* Add, reorder, rename and remove need a `planned` or `live` meeting. A closed
  meeting gives 409 `meeting_closed`.
* Remove gives 409 `agenda_item_has_vote` while the item has an open or closed vote.
  It deletes the draft and cancelled votes of the item first, each with a
  `vote_delete` audit entry.
* The Markdown body needs a `live` meeting, or a closed meeting whose protocol is
  still a draft. The `nonPublic` flag is open from the planning until the protocol
  leaves the draft.

Every change writes an audit entry (F12): `agenda_item_add`, `agenda_item_update`,
`agenda_item_remove` and `agenda_reorder`. A body edit of a live meeting is the
running minutes and its autosave is not audited. A body edit after the close is a
correction of the minutes and is audited, without the text.
"""

from __future__ import annotations

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

# The meeting states that accept a change of the agenda (O25).
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
        self.session = session

    async def _meeting(self, meeting_id: UUID) -> Meeting:
        meeting = (
            await self.session.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    @staticmethod
    def _assert_agenda_open(meeting: Meeting) -> None:
        """Refuse a change of the agenda structure after the close (O25).

        Raises:
            ConflictError: The meeting is closed (``meeting_closed``).
        """
        if meeting.status not in _AGENDA_OPEN:
            raise ConflictError(
                "the meeting is closed — its agenda can no longer change",
                code="meeting_closed",
            )

    async def _assert_minutes_open(self, meeting: Meeting, *, planned_ok: bool) -> None:
        """Refuse a body or ``nonPublic`` edit outside the minutes window (O22).

        The window is a ``live`` meeting, or a closed meeting whose protocol is still a
        draft. A ``planned`` meeting has no minutes yet, so only ``planned_ok`` (the
        ``nonPublic`` flag, which is planning work) passes there.

        Raises:
            ConflictError: The meeting has not started (``meeting_not_started``), or
                the protocol is no longer a draft (``protocol_locked``).
        """
        if meeting.status == "planned" and not planned_ok:
            raise ConflictError(
                "the meeting has not started — start it before taking minutes",
                code="meeting_not_started",
            )
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

    async def _vote_states(self, gremium_id: UUID) -> dict[UUID, State]:
        """Return the vote states whose `config.gremiumId` points at this Gremium."""
        states = (
            await self.session.scalars(select(State).where(State.kind == "vote"))
        ).all()
        out: dict[UUID, State] = {}
        for s in states:
            cfg = s.config if isinstance(s.config, dict) else {}
            if cfg.get("gremiumId") == str(gremium_id):
                out[s.id] = s
        return out

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
            # A free-text item has no application and carries its own title.
            title = title_of(app.data) if app is not None else r.title
            out.append(
                AgendaItemOut(
                    id=r.id,
                    applicationId=r.application_id,
                    title=title,
                    body=r.body,
                    position=r.position,
                    nonPublic=r.non_public,
                    stateLabel=state.label_i18n if state is not None else None,
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

        A rename needs a `planned` or `live` meeting (O25). The body needs a `live`
        meeting, or a closed meeting with a draft protocol (O22). `non_public` also
        passes on a `planned` meeting. A change writes `agenda_item_update` with the
        changed field names. The body counts only after the close.

        Raises:
            NotFoundError: The meeting has no agenda item with this id.
            ConflictError: The meeting state does not allow the change.
        """
        meeting = await self._meeting(meeting_id)
        row = await self.item(meeting_id, item_id)
        renames = title is not None and row.application_id is None
        if renames:
            self._assert_agenda_open(meeting)
        if body is not None:
            await self._assert_minutes_open(meeting, planned_ok=False)
        elif non_public is not None:
            await self._assert_minutes_open(meeting, planned_ok=True)
        changed: list[str] = []
        if body is not None and body != row.body:
            row.body = body
            # The live minutes autosave every second. Only a correction after the
            # close goes into the audit log.
            if meeting.status == "closed":
                changed.append("body")
        if renames and title is not None and title.strip() != row.title:
            row.title = title.strip()
            changed.append("title")
        if non_public is not None and non_public != row.non_public:
            row.non_public = non_public
            changed.append("nonPublic")
        if changed:
            await self._audit(
                AuditAction.AGENDA_ITEM_UPDATE, actor=actor, item=row, fields=changed
            )
        await self.session.flush()
        await self.session.commit()
        return await self.list(meeting_id)

    async def reorder(
        self, meeting_id: UUID, item_ids: list[UUID], *, actor: str | None = None
    ) -> list[AgendaItemOut]:
        """Set the agenda order to the given sequence of item ids.

        The method skips an id that does not belong to this meeting. It writes
        `agenda_reorder` with the new order of the item ids.

        Raises:
            NotFoundError: The meeting does not exist.
            ConflictError: The meeting is closed (O25).
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
        meeting = await self._meeting(meeting_id)
        vote_states = await self._vote_states(meeting.gremium_id)
        if not vote_states:
            return []
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
                .where(Application.current_state_id.in_(list(vote_states.keys())))
                .order_by(Application.created_at.desc())
            )
        ).all()
        out: list[AssignableApplicationOut] = []
        for app in apps:
            if app.id in existing:
                continue
            state = (
                vote_states.get(app.current_state_id)
                if app.current_state_id is not None
                else None
            )
            out.append(
                AssignableApplicationOut(
                    applicationId=app.id,
                    title=title_of(app.data),
                    stateLabel=state.label_i18n if state is not None else None,
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

        Returns:
            `True` when the method added an item, `False` when the application
            was already on the agenda.

        Raises:
            NotFoundError: The meeting or the application does not exist.
            ConflictError: The meeting is closed (O25), or the application is not in
                a vote state of the Gremium.
        """
        meeting = await self._meeting(meeting_id)
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

        # `populate_existing`: the flow engine moved the state with a bulk UPDATE in
        # this transaction. Read the current state from the database.
        app = await self.session.get(
            Application, application_id, populate_existing=True
        )
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        vote_states = await self._vote_states(meeting.gremium_id)
        if app.current_state_id not in vote_states:
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

    async def remove(
        self, meeting_id: UUID, item_id: UUID, *, actor: str
    ) -> list[AgendaItemOut]:
        """Remove an agenda item (F24, O25).

        The meeting must be `planned` or `live`. An open or closed vote of the item
        blocks the remove. The draft and cancelled votes of the item are deleted
        first, each with `vote_delete`. The remove writes `agenda_item_remove`. An
        unknown item id changes nothing, as before.

        Raises:
            NotFoundError: The meeting does not exist.
            ConflictError: The meeting is closed (``meeting_closed``), or the item has
                an open or closed vote (``agenda_item_has_vote``).
        """
        # Local import: the voting service imports the flow engine, and the flow
        # engine imports this module.
        from app.modules.voting.service import VotingService

        meeting = await self._meeting(meeting_id)
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
                row.id, actor=actor
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

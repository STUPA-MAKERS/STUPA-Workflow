"""Agenda service: applications ↔ meeting.

"Assignable" are applications whose current state is a vote state
(``kind=='vote'``) with ``config.gremiumId`` pointing at the meeting's gremium.
The agenda is ordered (``position``) and is the source of the protocol TOPs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.flow.models import State
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.livevote.schemas import AgendaItemOut, AssignableApplicationOut
from app.shared.errors import ConflictError, NotFoundError


def _title_of(data: dict[str, Any] | None) -> str | None:
    """Return the application title from the system field ``title`` (or ``None``)."""
    if not data:
        return None
    value = data.get("title")
    return value.strip() if isinstance(value, str) and value.strip() else None


class AgendaService:
    """Manage a meeting's agenda (assign/remove/list applications)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _meeting(self, meeting_id: UUID) -> Meeting:
        meeting = (
            await self.session.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _vote_states(self, gremium_id: UUID) -> dict[UUID, State]:
        """Vote states whose ``config.gremiumId`` points at this gremium."""
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
        """Load one agenda item of the meeting (404 if unknown)."""
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
                .order_by(MeetingAgendaItem.position)
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
            # Application item: title/status from the application; free-text item: ``title`` column.
            title = _title_of(app.data) if app is not None else r.title
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
    ) -> list[AgendaItemOut]:
        """Set an item's Markdown body, title and/or visibility.

        ``title`` only renames free-text items (application items inherit the
        application's title); ``non_public`` toggles redaction in the public
        protocol PDF.
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
        if body is not None:
            row.body = body
        if title is not None and row.application_id is None:
            row.title = title.strip()
        if non_public is not None:
            row.non_public = non_public
        await self.session.flush()
        await self.session.commit()
        return await self.list(meeting_id)

    async def reorder(
        self, meeting_id: UUID, item_ids: list[UUID]
    ) -> list[AgendaItemOut]:
        """Reorder agenda items into the given order."""
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
        for item_id in item_ids:
            row = rows.get(item_id)
            if row is not None:
                row.position = position
                position += 1
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
                    title=_title_of(app.data),
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
    ) -> list[AgendaItemOut]:
        """Add an agenda item: application (in a vote state of the gremium) or free text."""
        meeting = await self._meeting(meeting_id)
        if title is not None:
            # Free-text item (no application) — append directly.
            self.session.add(
                MeetingAgendaItem(
                    meeting_id=meeting_id,
                    application_id=None,
                    title=title.strip(),
                    position=await self._next_position(meeting_id),
                    non_public=non_public,
                )
            )
            await self.session.flush()
            await self.session.commit()
            return await self.list(meeting_id)

        app = await self.session.get(Application, application_id)
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
        if existing is None:
            self.session.add(
                MeetingAgendaItem(
                    meeting_id=meeting_id,
                    application_id=application_id,
                    position=await self._next_position(meeting_id),
                    non_public=non_public,
                )
            )
            await self.session.flush()
            await self.session.commit()
        return await self.list(meeting_id)

    async def remove(self, meeting_id: UUID, item_id: UUID) -> list[AgendaItemOut]:
        row = (
            await self.session.execute(
                select(MeetingAgendaItem).where(
                    MeetingAgendaItem.meeting_id == meeting_id,
                    MeetingAgendaItem.id == item_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await self.session.delete(row)
            await self.session.commit()
        return await self.list(meeting_id)

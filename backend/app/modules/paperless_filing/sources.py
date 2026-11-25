"""Find the files that the platform must file in Paperless.

Three events file a document: a protocol becomes final (§F/integrations/paperless/002516),
an Antrag enters an end state of the flow (§F/integrations/paperless/003110,
§F/integrations/paperless/002535), and a version of a Haushaltsplan comes into force
(§F/integrations/paperless/002518). An end state is a state with `is_terminal`, also the
state of a replaced Antrag, so an approved state on the way does not file a copy.
`new_filings` finds the events since the switch of their part went on. `backfill_filings`
finds the elements from before that have no document (§F/integrations/paperless/002530).
Both give only files without a job, and the unique key of the record stops a second job
when two runs race.

A part whose switch is off gives no file (§F/integrations/paperless/002512).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.applications.models import Application, StatusEvent
from app.modules.budget.plan_models import BudgetPlanVersion
from app.modules.files.models import Attachment
from app.modules.flow.models import State
from app.modules.meetings.models import Meeting
from app.modules.meetings.protocol_models import Protocol
from app.modules.paperless.connection import part_since
from app.modules.paperless.filings import NewFiling
from app.modules.paperless.models import PaperlessFiling, PaperlessSettings

#: The most events of one kind that one run opens jobs for. The next run takes the rest.
SCAN_LIMIT = 50

_BEGINNING: datetime | None = None


def application_title(data: object) -> str:
    """The title of an Antrag from its answers, or "Antrag" without one."""
    title = data.get("title") if isinstance(data, dict) else None
    return title.strip() if isinstance(title, str) and title.strip() else "Antrag"


def _has_job(kind: str, source_id: InstrumentedAttribute[UUID]) -> ColumnElement[bool]:
    """A job of this kind exists for the source record."""
    return exists().where(PaperlessFiling.kind == kind, PaperlessFiling.source_id == source_id)


def _has_event_job(
    kind: str,
    source_id: InstrumentedAttribute[UUID],
    source_at: InstrumentedAttribute[datetime | None],
) -> ColumnElement[bool]:
    """A job of this kind exists for the source record at this event."""
    return exists().where(
        PaperlessFiling.kind == kind,
        PaperlessFiling.source_id == source_id,
        PaperlessFiling.source_at == source_at,
    )


def _has_element_job(kind: str, element_id: InstrumentedAttribute[UUID]) -> ColumnElement[bool]:
    """A job of this kind exists for the element, from any event."""
    return exists().where(PaperlessFiling.kind == kind, PaperlessFiling.element_id == element_id)


def _after(
    column: InstrumentedAttribute[datetime | None], since: datetime | None
) -> tuple[ColumnElement[bool], ...]:
    return () if since is None else (column >= since,)


async def _protocols(
    session: AsyncSession, since: datetime | None, *, public: bool, actor: str | None
) -> list[NewFiling]:
    """The final protocols without a job for their internal or their public PDF.

    With ``since`` the job belongs to one finalization, so a protocol that becomes final
    again gets a new job (§F/integrations/paperless/002521). Without it a protocol with
    any job is left out.
    """
    kind = "protocol_public" if public else "protocol"
    key = Protocol.public_pdf_storage_key if public else Protocol.pdf_storage_key
    done = (
        _has_event_job(kind, Protocol.id, Protocol.finalized_at)
        if since is not None
        else _has_element_job(kind, Protocol.id)
    )
    rows = await session.execute(
        select(Protocol.id, Protocol.finalized_at, Meeting.title)
        .join(Meeting, Meeting.id == Protocol.meeting_id)
        .where(
            Protocol.status == "final",
            Protocol.finalized_at.is_not(None),
            key.is_not(None),
            *_after(Protocol.finalized_at, since),
            ~done,
        )
        .order_by(Protocol.finalized_at, Protocol.id)
        .limit(SCAN_LIMIT)
    )
    return [
        NewFiling(
            kind=kind,
            element_id=protocol_id,
            source_id=protocol_id,
            source_at=finalized_at,
            title=f"{title} (öffentlich)" if public else title,
            actor=actor,
        )
        for protocol_id, finalized_at, title in rows
        if finalized_at is not None
    ]


def _end_state() -> ColumnElement[bool]:
    """The state is an end state of the flow config (§F/integrations/paperless/003110)."""
    return State.is_terminal.is_(True)


async def _attachments(session: AsyncSession, events: Sequence[NewFiling]) -> list[NewFiling]:
    """The clean attachments of the Anträge in an end state that have no job.

    An attachment without a clean virus scan is left out
    (§F/integrations/paperless/002535).
    """
    by_application = {event.element_id: event for event in events}
    if not by_application:
        return []
    rows = (
        await session.scalars(
            select(Attachment)
            .where(
                Attachment.application_id.in_(by_application),
                Attachment.scanned.is_(True),
                Attachment.scan_result == "clean",
                Attachment.storage_key.is_not(None),
                ~_has_job("attachment", Attachment.id),
            )
            .order_by(Attachment.created_at, Attachment.id)
        )
    ).all()
    return [
        NewFiling(
            kind="attachment",
            element_id=event.element_id,
            source_id=row.id,
            source_at=event.source_at,
            title=f"{event.title} – {row.filename}",
            application_id=event.element_id,
            actor=event.actor,
        )
        for row in rows
        if row.application_id is not None
        and (event := by_application.get(row.application_id)) is not None
    ]


async def _new_decisions(session: AsyncSession, since: datetime) -> list[NewFiling]:
    """The changes into an end state since the switch went on that have no job, one job each."""
    rows = await session.execute(
        select(StatusEvent.id, StatusEvent.at, StatusEvent.actor, Application.id, Application.data)
        .join(State, State.id == StatusEvent.to_state_id)
        .join(Application, Application.id == StatusEvent.application_id)
        .where(
            _end_state(),
            StatusEvent.at >= since,
            ~_has_job("application", StatusEvent.id),
        )
        .order_by(StatusEvent.at, StatusEvent.id)
        .limit(SCAN_LIMIT)
    )
    return [
        NewFiling(
            kind="application",
            element_id=application_id,
            source_id=event_id,
            source_at=at,
            title=application_title(data),
            application_id=application_id,
            actor=actor,
        )
        for event_id, at, actor, application_id, data in rows
    ]


async def _old_decisions(session: AsyncSession, actor: str | None) -> list[NewFiling]:
    """The Anträge in an end state without a job, with their newest change into it."""
    newest = (
        select(func.max(StatusEvent.at))
        .where(
            StatusEvent.application_id == Application.id,
            StatusEvent.to_state_id == Application.current_state_id,
        )
        .correlate(Application)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(StatusEvent.id, StatusEvent.at, Application.id, Application.data)
        .join(
            StatusEvent,
            and_(
                StatusEvent.application_id == Application.id,
                StatusEvent.to_state_id == Application.current_state_id,
                StatusEvent.at == newest,
            ),
        )
        .join(State, State.id == Application.current_state_id)
        .where(_end_state(), ~_has_element_job("application", Application.id))
        .order_by(StatusEvent.at, StatusEvent.id)
        .limit(SCAN_LIMIT)
    )
    return [
        NewFiling(
            kind="application",
            element_id=application_id,
            source_id=event_id,
            source_at=at,
            title=application_title(data),
            application_id=application_id,
            actor=actor,
        )
        for event_id, at, application_id, data in rows
    ]


async def _plans(
    session: AsyncSession, since: datetime | None, actor: str | None
) -> list[NewFiling]:
    """The plan versions in force without a job.

    The title of the job is a placeholder; the job sets the title of the export when it
    builds the file.
    """
    rows = await session.execute(
        select(BudgetPlanVersion.id, BudgetPlanVersion.plan_id, BudgetPlanVersion.in_force_at)
        .where(
            BudgetPlanVersion.state == "in_force",
            BudgetPlanVersion.in_force_at.is_not(None),
            *_after(BudgetPlanVersion.in_force_at, since),
            ~_has_job("plan", BudgetPlanVersion.id),
        )
        .order_by(BudgetPlanVersion.in_force_at, BudgetPlanVersion.id)
        .limit(SCAN_LIMIT)
    )
    return [
        NewFiling(
            kind="plan",
            element_id=plan_id,
            source_id=version_id,
            source_at=in_force_at,
            title="Haushaltsplan",
            actor=actor,
        )
        for version_id, plan_id, in_force_at in rows
        if in_force_at is not None
    ]


def open_kinds(settings: PaperlessSettings) -> tuple[str, ...]:
    """The kinds of filing whose part is on. A job of another kind waits.

    A file of a ticket has no switch: a person files it by hand while the connection is
    on (§F/integrations/ticket-mail/002742).
    """
    connected = bool(settings.base_url and settings.token)
    return (
        *(("protocol", "protocol_public") if part_since(settings, "protocols") else ()),
        *(("application", "attachment") if part_since(settings, "applications") else ()),
        *(("plan",) if part_since(settings, "plans") else ()),
        *(("ticket_file",) if connected else ()),
    )


async def new_filings(session: AsyncSession, settings: PaperlessSettings) -> list[NewFiling]:
    """The files of the events since the switch of each part went on."""
    protocols = part_since(settings, "protocols")
    applications = part_since(settings, "applications")
    plans = part_since(settings, "plans")
    decisions = await _new_decisions(session, applications) if applications else []
    return [
        *(await _protocols(session, protocols, public=False, actor=None) if protocols else []),
        *(await _protocols(session, protocols, public=True, actor=None) if protocols else []),
        *decisions,
        *(await _attachments(session, decisions)),
        *(await _plans(session, plans, None) if plans else []),
    ]


async def backfill_filings(
    session: AsyncSession, settings: PaperlessSettings, actor: str
) -> list[NewFiling]:
    """The files of the elements that have no job, for each part whose switch is on."""
    protocols = part_since(settings, "protocols") is not None
    applications = part_since(settings, "applications") is not None
    plans = part_since(settings, "plans") is not None
    decisions = await _old_decisions(session, actor) if applications else []
    return [
        *(await _protocols(session, _BEGINNING, public=False, actor=actor) if protocols else []),
        *(await _protocols(session, _BEGINNING, public=True, actor=actor) if protocols else []),
        *decisions,
        *(await _attachments(session, decisions)),
        *(await _plans(session, _BEGINNING, actor) if plans else []),
    ]

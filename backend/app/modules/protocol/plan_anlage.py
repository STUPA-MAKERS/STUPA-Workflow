"""Append the plans on the agenda of a meeting to its protocol (§F/finance/budget/000876).

The finalize of a protocol calls `attach_plans` before it builds the Markdown. Each
agenda item of a Haushaltsplan gets the PDF of the plan as a stored document, and
`plan_reference` gives the line that the text of the item then carries. The embedded
PDFs of the protocol texts do the rest: the PDF is an Anlage of the protocol PDF, and
the public protocol shows it only with a public item.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.modules.budget.plan_export import PlanFile
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.media.refs import document_path
from app.modules.media.service import MediaService
from app.modules.meetings.agenda_service import agenda_order
from app.modules.meetings.models import MeetingAgendaItem
from app.modules.pdf.typst_client import TypstError
from app.modules.site_config.export_logo import (
    active_export_logo,
    export_render_assets,
    export_render_config,
)
from app.modules.voting.models import Vote
from app.shared.errors import BadRequestError, ServiceUnavailableError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage
    from app.modules.pdf.typst_client import TypstClient


def plan_reference(name: str, document_id: UUID) -> str:
    """Return the Markdown line that refers to the PDF of a plan."""
    label = name.replace("[", "(").replace("]", ")")
    return f"[{label}]({document_path(document_id)})"


def with_plan_reference(body: str, reference: str | None) -> str:
    """Return the text of an item with the reference to its plan below it."""
    return "\n\n".join(part for part in (body, reference) if part)


async def _vote_ids(session: AsyncSession, item_id: UUID) -> Sequence[UUID]:
    return (
        await session.scalars(
            select(Vote.id).where(Vote.agenda_item_id == item_id, Vote.status != "cancelled")
        )
    ).all()


async def _render(typst: TypstClient, session: AsyncSession, file: PlanFile) -> bytes:
    """Render the PDF of a plan with the export logo of the branding (spec 000891).

    Raises:
        BadRequestError: typst reported a permanent error (400).
        ServiceUnavailableError: typst failed for a short time (503).
    """
    logo = await active_export_logo(session)
    try:
        return await typst.render_pdf(
            file.source,
            variant="plan",
            config={**export_render_config(logo, footer=False), **file.config},
            assets=export_render_assets(logo),
        )
    except TypstError as exc:
        if not exc.retryable:
            raise BadRequestError(
                f"The plan could not be rendered: {exc}", code="render_failed"
            ) from exc
        raise ServiceUnavailableError("PDF rendering temporarily unavailable.") from exc


async def attach_plans(
    session: AsyncSession,
    storage: ObjectStorage | None,
    typst: TypstClient | None,
    meeting_id: UUID,
    today: date,
) -> None:
    """Store the PDF of each plan on the agenda and bind it to its agenda item.

    A plan with a vote gives the file that the open of the vote kept, a plan for a
    reading its state of now. The stored object is written before the commit of the
    finalize, because the render of the protocol reads it from the storage. Without a
    storage or a render service the method does nothing, like the render itself.

    Raises:
        BadRequestError: typst refused a plan (400).
        ServiceUnavailableError: typst or the storage failed (503).
    """
    if storage is None or typst is None:
        return
    items = (
        await session.scalars(
            select(MeetingAgendaItem)
            .where(MeetingAgendaItem.meeting_id == meeting_id)
            .order_by(*agenda_order())
        )
    ).all()
    budget = BudgetTreeService(session, storage=storage)
    media = MediaService(session, storage=storage)
    for item in items:
        version_id: UUID | None = getattr(item, "plan_version_id", None)
        file = await budget.plan_file_for_protocol(
            version_id, await _vote_ids(session, item.id), today
        )
        if file is not None:
            pdf = await _render(typst, session, file)
            item.plan_document_id = (await media.add_document(pdf, file.name)).id
    await session.flush()

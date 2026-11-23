"""Build the file of one filing with the data of its document.

A protocol gives its stored PDF, an attachment its stored file. The PDF of an Antrag and
of a Haushaltsplan renders anew, as the export does (§F/integrations/paperless/002517,
§F/integrations/paperless/002518). Each file carries the title, the date of its event,
the document type, the name of its Gremium and the address of its element in the
platform (§F/integrations/paperless/002519).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.access import Access
from app.modules.applications.models import Application
from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Principal
from app.modules.budget import plan_export
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import Budget
from app.modules.documents.router import application_pdf_filename
from app.modules.documents.service import ApplicationPdfService
from app.modules.files.models import Attachment
from app.modules.files.pdf_branding import (
    active_pdf_branding,
    export_render_assets,
    export_render_config,
)
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting
from app.modules.meetings.protocol_models import Protocol
from app.modules.paperless.models import PaperlessFiling
from app.modules.paperless_filing.sources import application_title
from app.modules.pdf.typst_client import TypstClient, TypstError
from app.modules.protocol.filename import protocol_pdf_filename
from app.modules.protocol.public import meeting_day
from app.settings import Settings
from app.shared.errors import AppError, NotFoundError

DocumentType = Literal["Protokoll", "Antrag", "Haushaltsplan"]

PDF = "application/pdf"


class BuildError(Exception):
    """The file of a filing could not be built.

    ``code`` is the short cause. ``final`` tells that a new try cannot repair it: the
    element or its file is gone, or the render service refuses the document.
    """

    def __init__(self, code: str, *, final: bool) -> None:
        """Keep the cause code and whether the failure is final."""
        super().__init__(code)
        self.code: str = code
        self.final: bool = final


@dataclass(frozen=True, slots=True)
class Prepared:
    """One file with the data of its document."""

    filename: str
    content: bytes
    mime: str
    title: str
    created: date
    document_type: DocumentType
    gremium: str | None
    link: str


def _system_reader() -> Principal:
    """The reader of the archive copy of an Antrag: it reads each field.

    No person stands behind this principal. The archive must hold the whole Antrag, so
    the copy hides no field.
    """
    return Principal(sub="system:paperless", roles=["admin"])


@dataclass(frozen=True, slots=True)
class FileBuilder:
    """Build the files of the filings, bound to one session of the worker."""

    session: AsyncSession
    storage: ObjectStorage | None
    typst: TypstClient | None
    settings: Settings

    def _day(self, moment: datetime) -> date:
        """The local day of an event."""
        return moment.astimezone(ZoneInfo(self.settings.local_timezone)).date()

    def _link(self, path: str) -> str:
        return f"{self.settings.public_base_url.rstrip('/')}{path}"

    async def _gremium(self, gremium_id: UUID | None) -> str | None:
        if gremium_id is None:
            return None
        return await self.session.scalar(select(Gremium.name).where(Gremium.id == gremium_id))

    async def _stored(self, key: str | None) -> bytes:
        """Read one object of the storage.

        Raises:
            BuildError: The object has no key (final) or the storage fails.
        """
        if key is None:
            raise BuildError("source_missing", final=True)
        if self.storage is None:
            raise BuildError("storage", final=False)
        try:
            return await self.storage.get(key)
        except StorageError as exc:
            raise BuildError("storage", final=False) from exc

    async def build(self, filing: PaperlessFiling) -> Prepared:
        """Build the file of a filing.

        Raises:
            BuildError: The element or its file is gone, or the file does not build.
        """
        match filing.kind:
            case "protocol":
                return await self._protocol(filing, public=False)
            case "protocol_public":
                return await self._protocol(filing, public=True)
            case "application":
                return await self._application(filing)
            case "attachment":
                return await self._attachment(filing)
            case _:
                return await self._plan(filing)

    async def _protocol(self, filing: PaperlessFiling, *, public: bool) -> Prepared:
        """The stored PDF of a final protocol.

        A protocol that left the finalization of this filing gives no file: the next
        finalization files its own.
        """
        protocol = await self.session.get(Protocol, filing.source_id)
        if (
            protocol is None
            or protocol.status != "final"
            or protocol.finalized_at != filing.source_at
        ):
            raise BuildError("source_missing", final=True)
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        if meeting is None:
            raise BuildError("source_missing", final=True)
        key = protocol.public_pdf_storage_key if public else protocol.pdf_storage_key
        return Prepared(
            filename=protocol_pdf_filename(meeting.title, meeting_day(meeting), public=public),
            content=await self._stored(key),
            mime=PDF,
            title=f"{meeting.title} (öffentlich)" if public else meeting.title,
            created=self._day(filing.source_at),
            document_type="Protokoll",
            gremium=await self._gremium(protocol.gremium_id),
            link=self._link(f"/meetings/{meeting.id}"),
        )

    async def _application(self, filing: PaperlessFiling) -> Prepared:
        """The PDF of an Antrag as the export renders it now."""
        pdfs = ApplicationPdfService(
            self.session, storage=self.storage, typst=self.typst, settings=self.settings
        )
        access = Access(
            application_id=filing.element_id, principal=_system_reader(), applicant=None
        )
        try:
            doc = await pdfs.reader_doc(ApplicationsService(self.session), access)
            content = await pdfs.render(doc)
        except NotFoundError as exc:
            raise BuildError("source_missing", final=True) from exc
        except AppError as exc:
            raise BuildError("render", final=exc.status == 400) from exc
        app = await self.session.get(Application, filing.element_id)
        return Prepared(
            filename=application_pdf_filename(doc.title, doc.received_on),
            content=content,
            mime=PDF,
            title=doc.title,
            created=self._day(filing.source_at),
            document_type="Antrag",
            gremium=await self._gremium(app.gremium_id if app is not None else None),
            link=self._link(f"/applications/{filing.element_id}"),
        )

    async def _attachment(self, filing: PaperlessFiling) -> Prepared:
        """One attachment of an Antrag, only with a clean virus scan."""
        attachment = await self.session.get(Attachment, filing.source_id)
        app = await self.session.get(Application, filing.element_id)
        if (
            attachment is None
            or app is None
            or attachment.application_id != app.id
            or not attachment.scanned
            or attachment.scan_result != "clean"
        ):
            raise BuildError("source_missing", final=True)
        return Prepared(
            filename=attachment.filename,
            content=await self._stored(attachment.storage_key),
            mime=attachment.mime,
            title=f"{application_title(app.data)} – {attachment.filename}",
            created=self._day(filing.source_at),
            document_type="Antrag",
            gremium=await self._gremium(app.gremium_id),
            link=self._link(f"/applications/{app.id}"),
        )

    async def _plan(self, filing: PaperlessFiling) -> Prepared:
        """The PDF of a plan version as the export renders it now."""
        if self.typst is None:
            raise BuildError("render", final=False)
        service = BudgetTreeService(self.session, storage=self.storage, settings=self.settings)
        try:
            plan = await service.plan_of_version(filing.source_id)
            export = await service.plan_export(filing.source_id, self._day(filing.source_at))
        except NotFoundError as exc:
            raise BuildError("source_missing", final=True) from exc
        branding = await active_pdf_branding(self.session, self.storage)
        try:
            content = await self.typst.render_pdf(
                plan_export.pdf_source(export),
                variant="plan",
                config={
                    **export_render_config(branding, footer=False),
                    **plan_export.pdf_config(export),
                },
                assets=export_render_assets(branding),
            )
        except TypstError as exc:
            raise BuildError("render", final=not exc.retryable) from exc
        gremium_id = await self.session.scalar(
            select(Budget.gremium_id).where(Budget.id == plan.budget_id)
        )
        return Prepared(
            filename=plan_export.export_filename(export.head, "pdf"),
            content=content,
            mime=PDF,
            title=export.head.title,
            created=self._day(filing.source_at),
            document_type="Haushaltsplan",
            gremium=await self._gremium(gremium_id),
            link=self._link(f"/budget/plan?budget={plan.budget_id}&fy={plan.fiscal_year_id}"),
        )

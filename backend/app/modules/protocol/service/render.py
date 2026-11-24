"""The render of the internal and the public PDF through typst, and their storage."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from app.modules.applications.service import ApplicationsService
from app.modules.documents.service import ANLAGE_MARK, ApplicationPdfService
from app.modules.files.cd_resolver import cd_render_config, resolve_cd_variant_by_key
from app.modules.files.pdf_branding import (
    active_pdf_branding,
    footer_render_assets,
    footer_render_config,
)
from app.modules.files.storage import StorageError
from app.modules.media.service import MediaService
from app.modules.meetings.models import MeetingAgendaItem
from app.modules.meetings.protocol_models import Protocol
from app.modules.pdf.typst_client import TypstError
from app.modules.protocol.markdown import protocol_variant_for
from app.modules.protocol.public import PublicSnapshot, apply_public_snapshot
from app.modules.protocol.service.common import (
    _upload,
    protocol_public_storage_key,
    protocol_storage_key,
)
from app.modules.protocol.service.document import DocumentOps
from app.settings import get_settings
from app.shared.errors import BadRequestError, ServiceUnavailableError


class RenderOps(DocumentOps):
    """PDF render and storage."""

    async def _render_both(
        self, protocol: Protocol, *, mail_public: bool
    ) -> tuple[tuple[tuple[str, bytes], ...], bytes | None]:
        """Render the internal and the public PDF and store the public snapshot.

        Returns:
            The uploads, and the PDF for the mail: the public one when a non-public
            item or a blackout mark exists, else the internal one.
        """
        internal_md = await self._build_document(protocol, public=False)
        internal_pdf = await self._render_pdf(protocol, internal_md, public=False)
        snapshot = PublicSnapshot()
        public_md = await self._build_document(protocol, public=True, snapshot=snapshot)
        public_pdf = await self._render_pdf(protocol, public_md, public=True)
        apply_public_snapshot(protocol, snapshot, public_pdf)
        uploads = (
            *_upload(protocol_storage_key(protocol.id), internal_pdf),
            *_upload(protocol_public_storage_key(protocol.id), public_pdf),
        )
        return uploads, (public_pdf if mail_public else internal_pdf)

    async def _render_internal(
        self, protocol: Protocol
    ) -> tuple[tuple[tuple[str, bytes], ...], bytes | None]:
        """Render the internal PDF only, which the mail then carries."""
        markdown = await self._build_document(protocol)
        pdf = await self._render_pdf(protocol, markdown)
        return _upload(protocol_storage_key(protocol.id), pdf), pdf

    async def _anlage_assets(self, protocol: Protocol, *, public: bool) -> dict[str, bytes]:
        """Render the Antrag Anlagen of the TOPs of the meeting (spec 000884).

        Each TOP of an Antrag appends the Antrag PDF in the version that the Sitzung
        treated. The public variant blacks out the personal data and leaves out the
        Anlage of a non-public TOP.
        """
        items = list(
            (
                await self.session.scalars(
                    select(MeetingAgendaItem).where(
                        MeetingAgendaItem.meeting_id == protocol.meeting_id,
                        MeetingAgendaItem.application_id.is_not(None),
                    )
                )
            ).all()
        )
        if not items:
            return {}
        pdfs = ApplicationPdfService(
            self.session,
            storage=self.storage,
            typst=self.typst,
            settings=self.settings or get_settings(),
        )
        return await pdfs.anlage_assets(ApplicationsService(self.session), items, public=public)

    async def _render_pdf(
        self,
        protocol: Protocol,
        markdown: str,
        *,
        public: bool = False,
        watermark: str | None = None,
    ) -> bytes | None:
        """Render the Markdown with typst and return the PDF bytes.

        `watermark` puts a text across every page (the draft that goes to the members,
        spec 000925). Such a render is no stored version: it sets no key column.

        The render runs BEFORE the commit. The method sets the key column but does
        NOT upload. The storage `put` runs after the commit in `_store`.
        `public=True` sets `public_pdf_storage_key` instead of `pdf_storage_key`.

        Storage is the on/off switch: without it, finalize continues without a PDF (demo
        or contract CI without MinIO). The protocol uses the CD key that it snapshots
        from its gremium at creation, so it keeps its design after the gremium moves to
        another one. A protocol always renders with a protocol variant: the design
        contributes logos, but it does not pick the document shape, because a report
        shape loses the TOP numbering, the vote boxes and the signature page. The
        footer graphic of the PDF branding (spec 000892) goes on each page. The
        uploaded images of the text go next to the logos. An image that is missing or
        exceeds the budget stays out, and the PDF shows its alt text. The body is
        user-written. The render service converts it into data before Typst sees it, so
        no part of it runs as code there.

        A typst 4xx is a permanent input error, for example a malformed formula. It is
        not retried and gives the scrubbed reason instead of a misleading 503. A 5xx or
        a transport error stays transient.

        Returns:
            The PDF bytes, or `None` when storage is off (dev). The method then
            renders nothing.

        Raises:
            BadRequestError: typst reported a permanent error (400).
            ServiceUnavailableError: typst failed for a short time (503). The draft
                survives.
        """
        if self.storage is None or self.typst is None:
            return None
        try:
            cd = await resolve_cd_variant_by_key(self.session, self.storage, protocol.cd_variant)
            variant = protocol_variant_for(protocol.cd_variant)
            branding = await active_pdf_branding(self.session, self.storage)
            config = {
                **(cd_render_config(cd) if cd else {}),
                **footer_render_config(branding),
                **({"watermark": watermark} if watermark else {}),
            }
            media = MediaService(self.session, storage=self.storage)
            images = await media.render_assets(markdown)
            documents = await media.render_documents(markdown)
            anlagen = (
                await self._anlage_assets(protocol, public=public)
                if ANLAGE_MARK in markdown
                else {}
            )
            assets = {
                **(cd.assets if cd else {}),
                **footer_render_assets(branding),
                **images,
                **documents,
                **anlagen,
            } or None
            pdf = await self.typst.render_pdf(
                markdown, variant=variant, config=config, assets=assets
            )
        except TypstError as exc:
            if not exc.retryable:
                raise BadRequestError(
                    f"Protocol could not be rendered: {exc}", code="render_failed"
                ) from exc
            raise ServiceUnavailableError("Protocol rendering temporarily unavailable.") from exc
        if watermark:
            return pdf
        key = (
            protocol_public_storage_key(protocol.id)
            if public
            else protocol_storage_key(protocol.id)
        )
        if public:
            protocol.public_pdf_storage_key = key
        else:
            protocol.pdf_storage_key = key
        return pdf

    async def _store(self, uploads: Sequence[tuple[str, bytes]]) -> None:
        """Upload the rendered PDFs to object storage AFTER a successful commit.

        The MinIO object appears only now, so a failed commit leaves no orphaned
        object. With storage off, `uploads` is empty because `_render_pdf` returned
        `None`.

        The 503 message does not name the storage path.

        Raises:
            ServiceUnavailableError: The storage failed for a short time (503). The
                protocol is already committed as `final`. A repeated `finalize` is a
                no-op through the `status=='final'` idempotency.
        """
        if self.storage is None:
            return
        try:
            for key, pdf in uploads:
                await self.storage.put(key, pdf, "application/pdf")
        except StorageError as exc:
            raise ServiceUnavailableError("Protocol rendering temporarily unavailable.") from exc

    async def _stored_pdf(self, key: str) -> bytes | None:
        """Read a stored PDF to learn its size, or `None` without storage or on an error."""
        if self.storage is None:
            return None
        try:
            return await self.storage.get(key)
        except StorageError:
            return None

"""Collect the data of an Antrag PDF and render it with the typst service.

`ApplicationPdfService` reads an Antrag the way a reader sees it, builds the Markdown
with `build_application_document` and renders it in the design of the Gremium of the
Antrag. Two callers use it:

* The export route (`GET /api/applications/{id}/pdf`) renders the current version for
  the reader. It reads through `ApplicationsService.get_for`, so the PDF shows the same
  fields as the detail page (spec 000882).
* The protocol renders a frozen version as an Anlage (spec 000884). It reads one
  `SubmissionVersion` and leaves out the status and the decision, because the protocol
  holds the vote result. The public variant prints the ``isPII`` answers and the
  applicant as a black bar (spec 000886).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import KW_ONLY, dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.application_types.models import ApplicationType
from app.modules.applications.access import Access
from app.modules.applications.decision import valid_decision
from app.modules.applications.models import Applicant, Application, SubmissionVersion
from app.modules.applications.schemas import ApplicationOut
from app.modules.applications.service import ApplicationsService
from app.modules.applications.service.service_base import pii_keys_for_type
from app.modules.documents.application_markdown import (
    ApplicationDoc,
    DecisionView,
    FormSection,
    anlage_link,
    build_application_document,
)
from app.modules.files.models import Attachment
from app.modules.files.pdf_branding import (
    active_pdf_branding,
    export_render_assets,
    export_render_config,
)
from app.modules.files.storage import ObjectStorage
from app.modules.forms.schemas import EffectiveFormOut
from app.modules.gremien.models import Gremium
from app.modules.media.refs import document_path
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.pdf.typst_client import TypstClient, TypstError
from app.modules.voting.models import Vote
from app.settings import Settings
from app.shared.errors import BadRequestError, NotFoundError, ServiceUnavailableError
from app.shared.i18n import resolve_i18n

LANG = "de"
"""The language of the PDF."""

logger = logging.getLogger("app.documents")

#: The results of a motion vote as the Antrag PDF prints them.
_RESULTS: dict[str, str] = {
    "passed": "Angenommen",
    "rejected": "Abgelehnt",
    "tie": "Stimmengleichheit",
}

_ANLAGE_NAMESPACE = uuid.UUID("6f1c4d1e-9a51-4c43-8f0e-2b7d3c9a8e15")
"""The namespace of the ids of the Antrag Anlagen. An id is no row: it only joins the
reference in the protocol text to its render asset."""


def anlage_id(item_id: uuid.UUID, *, public: bool) -> uuid.UUID:
    """Return the id of the Antrag Anlage of one agenda item and one protocol variant.

    The id is stable, so the reference in the text and the asset of the render meet
    without state between the two steps. The variants get two ids, because their PDFs
    differ.
    """
    return uuid.uuid5(_ANLAGE_NAMESPACE, f"{item_id}:{'public' if public else 'internal'}")


ANLAGE_MARK = "[Antrag "
"""The start of the reference of an Antrag Anlage. The protocol render looks for the
Anlagen only in a text that holds it."""


def anlage_reference(item_id: uuid.UUID, title: str, *, public: bool) -> str:
    """Write the reference line of the Antrag Anlage of one agenda item (spec 000884)."""
    return anlage_link(title, document_path(anlage_id(item_id, public=public)))


def _uuid_or_none(value: str) -> uuid.UUID | None:
    """Parse a stored voter group as a Gremium id; another value gives `None`."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _answer_refs(answer: object) -> tuple[str, ...]:
    """Return the attachment ids that a form answer refers to: a string or a list of them."""
    match answer:
        case str():
            return (answer,)
        case list():
            return tuple(v for v in answer if isinstance(v, str))
        case _:
            return ()


def _sections(form: EffectiveFormOut) -> tuple[FormSection, ...]:
    return tuple(
        FormSection(label=resolve_i18n(s.label, LANG) or s.key, fields=tuple(s.fields))
        for s in form.sections
    )


def _title(data: Mapping[str, Any]) -> str:
    title = data.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else "Antrag"


@dataclass(frozen=True, slots=True)
class ApplicationPdfService:
    """Build and render the PDF of one Antrag.

    Attributes:
        session: The database session of the request.
        storage: The object storage, for the PDF branding.
        typst: The client of the render service, or `None` when it is not configured.
        settings: The settings, for the local time zone.
    """

    session: AsyncSession
    _: KW_ONLY
    storage: ObjectStorage | None
    typst: TypstClient | None
    settings: Settings

    def _received_on(self, app: Application) -> date:
        """The date of receipt: the captured date, else the local day of the creation."""
        created: datetime = app.created_at
        return app.received_on or created.astimezone(ZoneInfo(self.settings.local_timezone)).date()

    async def _type_name(self, type_id: uuid.UUID) -> str | None:
        names = await self.session.scalar(
            select(ApplicationType.name_i18n).where(ApplicationType.id == type_id)
        )
        return resolve_i18n(names, LANG) if isinstance(names, dict) else None

    async def _signs(self, type_id: uuid.UUID) -> bool:
        """Tell whether the Antrag PDF of the type ends with the signature section."""
        return bool(
            await self.session.scalar(
                select(ApplicationType.pdf_signatures).where(ApplicationType.id == type_id)
            )
        )

    async def _gremium(self, gremium_id: uuid.UUID | None) -> Gremium | None:
        return await self.session.get(Gremium, gremium_id) if gremium_id is not None else None

    async def _file_names(
        self, app_id: uuid.UUID, data: Mapping[str, Any], hidden: frozenset[str]
    ) -> tuple[str, ...]:
        """List the names of the files of the Antrag, without the files of hidden fields.

        A file belongs to a hidden field when its ``field_key`` names the field or when
        the answer of the field refers to its id, as in the attachment list. Files of
        comments are not part of the Antrag.
        """
        refs = frozenset(ref for key in hidden for ref in _answer_refs(data.get(key)))
        rows = (
            await self.session.scalars(
                select(Attachment)
                .where(Attachment.application_id == app_id, Attachment.comment_id.is_(None))
                .order_by(Attachment.created_at)
            )
        ).all()
        return tuple(
            a.filename
            for a in rows
            if a.field_key not in hidden and str(a.id) not in refs and a.filename
        )

    async def _vote_decision(self, application_id: uuid.UUID) -> DecisionView | None:
        """Build the decision of an Antrag from its newest closed vote (spec 000881).

        A passed vote without a deviation writes no decision row, and a rejected vote
        writes none either. The PDF still names the Gremium, the day and the result.
        """
        vote = await self.session.scalar(
            select(Vote)
            .where(
                Vote.application_id == application_id,
                Vote.status == "closed",
                Vote.result.in_(tuple(_RESULTS)),
            )
            .order_by(func.coalesce(Vote.closed_at, Vote.closes_at, Vote.opens_at).desc())
            .limit(1)
        )
        moment = (vote.closed_at or vote.closes_at or vote.opens_at) if vote is not None else None
        if vote is None or moment is None:
            return None
        meeting = (
            await self.session.get(Meeting, vote.meeting_id)
            if vote.meeting_id is not None
            else None
        )
        gremium = await self._gremium(
            meeting.gremium_id if meeting is not None else _uuid_or_none(vote.eligible_group)
        )
        return DecisionView(
            approved_amount=None,
            conditions=(),
            decided_at=moment,
            gremium_name=gremium.name if gremium is not None else None,
            result=_RESULTS[vote.result or ""],
            approved=vote.result == "passed",
        )

    async def reader_doc(self, apps: ApplicationsService, access: Access) -> ApplicationDoc:
        """Build the document of the current version as the reader of `access` sees it."""
        out: ApplicationOut = await apps.get_for(access)
        app = await self.session.get(Application, access.application_id)
        if app is None:  # pragma: no cover - get_for raised already
            raise NotFoundError("Application not found.")
        form = await apps.effective_form(
            access.application_id, allow_unconfirmed=access.is_owning_applicant
        )
        gremium = await self._gremium(app.gremium_id)
        hidden = frozenset(out.hidden_keys)
        applicant = (out.applicant.name or None) if out.applicant is not None else out.submitted_by
        applicant_email = (out.applicant.email or None) if out.applicant is not None else None
        # The PDF names a Gremium only for a decision by a vote: the Gremium that ran
        # the vote. The applicant view hides the vote id, so the row tells it.
        row = await valid_decision(self.session, app.id) if out.decision is not None else None
        voted = row is not None and row.vote_id is not None
        decision = (
            DecisionView(
                approved_amount=out.decision.approved_amount,
                conditions=tuple(out.decision.conditions),
                decided_at=out.decision.decided_at,
                gremium_name=out.decision.gremium_name if voted else None,
                result=_RESULTS["passed"] if voted else None,
            )
            if out.decision is not None
            else await self._vote_decision(app.id)
        )
        return ApplicationDoc(
            title=_title(out.data),
            type_name=await self._type_name(app.type_id),
            gremium_name=gremium.name if gremium is not None else None,
            state_label=resolve_i18n(out.state.label, LANG) if out.state is not None else None,
            received_on=self._received_on(app),
            applicant=applicant,
            applicant_email=applicant_email,
            version=out.version,
            sections=_sections(form),
            data=out.data,
            context={"has_budget": form.has_budget},
            currency=out.currency or "EUR",
            hidden_keys=hidden,
            files=await self._file_names(app.id, app.data, hidden),
            decision=decision,
            signatures=await self._signs(app.type_id),
        )

    async def version_doc(
        self,
        apps: ApplicationsService,
        application_id: uuid.UUID,
        version: int | None,
        *,
        public: bool,
    ) -> ApplicationDoc | None:
        """Build the document of one frozen version for the protocol Anlage.

        `version=None` takes the current version. The document has no status and no
        decision. The public variant prints the ``isPII`` answers, the files of the
        ``isPII`` fields and the applicant as a black bar.

        Returns:
            The document, or `None` when the Antrag or the version no longer exists.
        """
        app = await self.session.get(Application, application_id)
        if app is None:
            return None
        row = (
            await self.session.scalar(
                select(SubmissionVersion).where(
                    SubmissionVersion.application_id == application_id,
                    SubmissionVersion.version == version,
                )
            )
            if version is not None
            else None
        )
        data: Mapping[str, Any] = row.data if row is not None else app.data
        number = (
            row.version
            if row is not None
            else await self.session.scalar(
                select(func.coalesce(func.max(SubmissionVersion.version), 1)).where(
                    SubmissionVersion.application_id == application_id
                )
            )
        )
        form = await apps.effective_form(application_id)
        gremium = await self._gremium(app.gremium_id)
        pii = (
            frozenset(await pii_keys_for_type(self.session, app.type_id)) if public else frozenset()
        )
        applicant = await self.session.scalar(
            select(Applicant).where(Applicant.application_id == application_id)
        )
        return ApplicationDoc(
            title=_title(data),
            type_name=await self._type_name(app.type_id),
            gremium_name=gremium.name if gremium is not None else None,
            state_label=None,
            received_on=self._received_on(app),
            applicant=(applicant.name or None) if applicant is not None else None,
            applicant_email=(applicant.email or None) if applicant is not None else None,
            version=int(number or 1),
            sections=_sections(form),
            data=data,
            context={"has_budget": form.has_budget},
            currency=app.currency or "EUR",
            redacted_keys=pii,
            redact_applicant=public,
            files=await self._file_names(app.id, data, pii),
        )

    async def frozen_version(self, item: MeetingAgendaItem) -> int | None:
        """Return the version of the Antrag that the Sitzung treated (spec 000885).

        That is the version that was current when the last vote of the TOP opened, else
        the one that was current when the TOP closed. A TOP without both gives `None`,
        which means the current version at the finalize. A cancelled vote does not
        count, because the Gremium did not decide on it.
        """
        if item.application_id is None:
            return None
        opened = await self.session.scalar(
            select(func.max(Vote.opens_at)).where(
                Vote.agenda_item_id == item.id, Vote.status != "cancelled"
            )
        )
        moment = opened or item.done_at
        if moment is None:
            return None
        return await self.session.scalar(
            select(func.max(SubmissionVersion.version)).where(
                SubmissionVersion.application_id == item.application_id,
                SubmissionVersion.at <= moment,
            )
        )

    async def anlage_assets(
        self, apps: ApplicationsService, items: list[MeetingAgendaItem], *, public: bool
    ) -> dict[str, bytes]:
        """Render the Antrag Anlagen of the agenda items as typst assets.

        An item without an Antrag gets none, and so does a non-public item of the public
        variant (spec 000867). An Antrag that is gone or that does not render is left
        out; typst then prints "Anlage nicht eingebunden" at its reference, so an Anlage
        never makes the protocol render fail (spec 000868).

        Returns:
            ``{"doc-<id>.pdf": bytes}`` with the ids of `anlage_id`.
        """
        wanted = [
            item
            for item in items
            if item.application_id is not None and not (public and item.non_public)
        ]
        rendered = [(item, await self._anlage_pdf(apps, item, public=public)) for item in wanted]
        return {
            f"doc-{anlage_id(item.id, public=public)}.pdf": pdf
            for item, pdf in rendered
            if pdf is not None
        }

    async def _anlage_pdf(
        self, apps: ApplicationsService, item: MeetingAgendaItem, *, public: bool
    ) -> bytes | None:
        """Render the Anlage of one item, or `None` when it cannot be rendered."""
        if item.application_id is None:  # pragma: no cover - the caller filters
            return None
        doc = await self.version_doc(
            apps, item.application_id, await self.frozen_version(item), public=public
        )
        if doc is None:
            return None
        try:
            return await self.render(doc)
        except (BadRequestError, ServiceUnavailableError):
            logger.warning(
                "antrag anlage not rendered", extra={"application_id": str(item.application_id)}
            )
            return None

    async def render(self, doc: ApplicationDoc) -> bytes:
        """Render a document with the export logo and the footer graphic (specs 000891, 000892).

        Raises:
            ServiceUnavailableError: The render service is not configured or failed for
                a short time (503).
            BadRequestError: The render service refused the document (400).
        """
        if self.typst is None:
            raise ServiceUnavailableError("PDF rendering is not available.")
        branding = await active_pdf_branding(self.session, self.storage)
        try:
            return await self.typst.render_pdf(
                build_application_document(doc),
                variant=None,
                config=export_render_config(branding, footer=True),
                assets=export_render_assets(branding),
            )
        except TypstError as exc:
            if not exc.retryable:
                raise BadRequestError(
                    f"Application could not be rendered: {exc}", code="render_failed"
                ) from exc
            raise ServiceUnavailableError("PDF rendering temporarily unavailable.") from exc

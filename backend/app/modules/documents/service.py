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
from app.modules.applications.models import Applicant, Application, SubmissionVersion
from app.modules.applications.schemas import ApplicationOut
from app.modules.applications.service import ApplicationsService
from app.modules.applications.service.service_base import pii_keys_for_type
from app.modules.documents.application_markdown import (
    ApplicationDoc,
    DecisionView,
    FormSection,
    build_application_document,
)
from app.modules.documents.cd_resolver import (
    cd_render_config,
    cd_variant_key_for_gremium,
    resolve_cd_variant_by_key,
)
from app.modules.files.models import Attachment
from app.modules.files.storage import ObjectStorage
from app.modules.forms.schemas import EffectiveFormOut
from app.modules.gremien.models import Gremium
from app.modules.pdf.typst_client import TypstClient, TypstError
from app.settings import Settings
from app.shared.errors import BadRequestError, NotFoundError, ServiceUnavailableError
from app.shared.i18n import resolve_i18n

LANG = "de"
"""The language of the PDF."""


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


def _applicant_line(name: str | None, email: str | None) -> str | None:
    """Write the applicant as `Name (E-Mail)`, the part that is known, or nothing."""
    match (name or None, email or None):
        case (None, None):
            return None
        case (str() as n, None):
            return n
        case (None, str() as e):
            return e
        case (n, e):
            return f"{n} ({e})"


@dataclass(frozen=True, slots=True)
class ApplicationPdfService:
    """Build and render the PDF of one Antrag.

    Attributes:
        session: The database session of the request.
        storage: The object storage, for the uploaded logos of the design.
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
        applicant = (
            _applicant_line(out.applicant.name, out.applicant.email)
            if out.applicant is not None
            else out.submitted_by
        )
        decision = (
            DecisionView(
                approved_amount=out.decision.approved_amount,
                conditions=tuple(out.decision.conditions),
                decided_at=out.decision.decided_at,
                gremium_name=out.decision.gremium_name,
            )
            if out.decision is not None
            else None
        )
        return ApplicationDoc(
            title=_title(out.data),
            type_name=await self._type_name(app.type_id),
            gremium_name=gremium.name if gremium is not None else None,
            cd_variant=await cd_variant_key_for_gremium(self.session, gremium),
            state_label=resolve_i18n(out.state.label, LANG) if out.state is not None else None,
            received_on=self._received_on(app),
            applicant=applicant,
            version=out.version,
            sections=_sections(form),
            data=out.data,
            context={"has_budget": form.has_budget},
            currency=out.currency or "EUR",
            hidden_keys=hidden,
            files=await self._file_names(app.id, app.data, hidden),
            decision=decision,
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
            cd_variant=await cd_variant_key_for_gremium(self.session, gremium),
            state_label=None,
            received_on=self._received_on(app),
            applicant=(
                _applicant_line(applicant.name, applicant.email) if applicant is not None else None
            ),
            version=int(number or 1),
            sections=_sections(form),
            data=data,
            context={"has_budget": form.has_budget},
            currency=app.currency or "EUR",
            redacted_keys=pii,
            redact_applicant=public,
            files=await self._file_names(app.id, data, pii),
        )

    async def render(self, doc: ApplicationDoc) -> bytes:
        """Render a document in the design of its Gremium.

        Raises:
            ServiceUnavailableError: The render service is not configured or failed for
                a short time (503).
            BadRequestError: The render service refused the document (400).
        """
        if self.typst is None:
            raise ServiceUnavailableError("PDF rendering is not available.")
        cd = await resolve_cd_variant_by_key(self.session, self.storage, doc.cd_variant)
        variant = f"protocol-{doc.cd_variant}" if doc.cd_variant in {"stupa", "asta"} else None
        config = cd_render_config(cd) if cd else None
        assets = dict(cd.assets) if cd else None
        try:
            return await self.typst.render_pdf(
                build_application_document(doc),
                variant=variant,
                config=config,
                assets=assets or None,
            )
        except TypstError as exc:
            if not exc.retryable:
                raise BadRequestError(
                    f"Application could not be rendered: {exc}", code="render_failed"
                ) from exc
            raise ServiceUnavailableError("PDF rendering temporarily unavailable.") from exc

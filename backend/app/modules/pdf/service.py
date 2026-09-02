"""pdf service: job lifecycle + application-document loading.

The module keeps two responsibilities apart on purpose:

* API side, bound to an ``AsyncSession``: ``create_application_job`` creates the
  ``render_job`` row in state ``pending``. ``get_job`` reads the status and, on
  success, builds a short-lived signed result URL. The render itself runs in the
  worker.
* Data loading: ``load_application_doc`` pulls fields, values, timeline and an optional
  vote result from the DB. It returns a plain ``ApplicationDoc``. The worker hands that
  document to ``app.modules.pdf.markdown``, which needs no DB and is unit-tested.

The render-pipeline code (pytex → MinIO) lives in ``app.modules.pdf.render``, so the
infra dependencies are injected worker-side only.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.cd_resolver import cd_variant_key_for_gremium
from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Applicant, Application, StatusEvent
from app.modules.applications.service.service_base import _field_from_row
from app.modules.files.storage import ObjectStorage
from app.modules.flow.models import State
from app.modules.forms.models import FormField
from app.modules.pdf.markdown import ApplicationDoc, TimelineItem, VoteResult
from app.modules.pdf.models import JOB_KIND_APPLICATION_PDF, RenderJob
from app.modules.pdf.schemas import JobOut
from app.modules.voting.models import Vote
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError
from app.shared.i18n import resolve_i18n


class PdfService:
    """DB-backed render-job operations + application-document assembly."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_application_job(
        self, application_id: UUID, *, idempotency_key: str | None = None
    ) -> RenderJob:
        """Create a ``render_job`` in state ``pending`` for an application.

        With an ``idempotency_key`` set (flow action ``exportPdf``) the service reuses
        an existing job that has the same key, so nothing renders twice.

        Raises:
            NotFoundError: The application does not exist.
        """
        app = await self.session.get(Application, application_id)
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        if idempotency_key is not None:
            existing = await self.session.scalar(
                select(RenderJob).where(RenderJob.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing
        job = RenderJob(
            kind=JOB_KIND_APPLICATION_PDF,
            application_id=application_id,
            status="pending",
            idempotency_key=idempotency_key,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_job(self, job_id: UUID) -> RenderJob:
        job = await self.session.get(RenderJob, job_id)
        if job is None:
            raise NotFoundError(f"job {job_id} not found")
        return job

    def to_out(
        self,
        job: RenderJob,
        *,
        storage: ObjectStorage | None = None,
    ) -> JobOut:
        """Convert the job to ``JobOut``.

        A finished job carries the APP-RELATIVE download route, not a presigned MinIO
        URL. MinIO sits on the internal Docker network, so a presigned S3 URL binds a
        host the browser cannot resolve. ``GET /api/jobs/{id}/download`` streams the
        bytes instead, the same way the attachment download does.

        ``storage`` stays in the signature because the download route only works when
        object storage is configured. A stack without it must not advertise a link.
        """
        result_url: str | None = None
        if job.status == "done" and job.storage_key is not None and storage is not None:
            result_url = f"/api/jobs/{job.id}/download"
        return JobOut(
            id=job.id,
            kind=job.kind or JOB_KIND_APPLICATION_PDF,
            status=job.status,
            applicationId=job.application_id,
            resultUrl=result_url,
            error=job.error,
        )

    async def load_application_doc(self, application_id: UUID) -> ApplicationDoc:
        """Load fields, values, timeline and an optional vote result into the document."""
        app = await self.session.get(Application, application_id)
        if app is None:
            raise NotFoundError(f"application {application_id} not found")

        app_type = await self.session.get(ApplicationType, app.type_id)
        gremium = (
            await self.session.get(Gremium, app.gremium_id)
            if app.gremium_id is not None
            else None
        )
        default_lang = gremium.default_lang if gremium is not None else "de"
        lang = app.lang or default_lang

        type_name = (
            resolve_i18n(app_type.name_i18n, lang, default_lang)
            if app_type is not None
            else None
        ) or (app_type.key if app_type is not None else "Antrag")

        fields = await self._fields(app.form_version_id)
        applicant_name = await self.session.scalar(
            select(Applicant.name).where(Applicant.application_id == application_id)
        )
        timeline = await self._timeline(application_id, lang, default_lang)
        vote = await self._vote_result(application_id, lang, default_lang)

        return ApplicationDoc(
            application_id=str(application_id),
            type_name=type_name,
            gremium_slug=gremium.slug if gremium is not None else None,
            cd_variant=await cd_variant_key_for_gremium(self.session, gremium),
            gremium_id=gremium.id if gremium is not None else None,
            lang=lang,
            default_lang=default_lang,
            fields=fields,
            data=dict(app.data),
            applicant_name=applicant_name,
            created_at=app.created_at,
            timeline=timeline,
            vote=vote,
        )

    async def _fields(self, form_version_id: UUID) -> list[FormFieldDef]:
        rows = (
            await self.session.scalars(
                select(FormField)
                .where(FormField.form_version_id == form_version_id)
                .order_by(FormField.order)
            )
        ).all()
        return [_field_from_row(r) for r in rows]

    async def _timeline(
        self, application_id: UUID, lang: str, default_lang: str
    ) -> list[TimelineItem]:
        rows = (
            await self.session.execute(
                select(StatusEvent, State)
                .join(State, State.id == StatusEvent.to_state_id)
                .where(StatusEvent.application_id == application_id)
                .order_by(StatusEvent.at)
            )
        ).all()
        items: list[TimelineItem] = []
        for event, state in rows:
            label = resolve_i18n(state.label_i18n, lang, default_lang) or state.key
            items.append(TimelineItem(at=event.at, state_label=label, note=event.note))
        return items

    async def _vote_result(
        self, application_id: UUID, lang: str, default_lang: str
    ) -> VoteResult | None:
        """Latest closed vote of the application (with a result), else ``None``."""
        vote = await self.session.scalar(
            select(Vote)
            .where(Vote.application_id == application_id, Vote.result.is_not(None))
            .order_by(Vote.created_at.desc())
            .limit(1)
        )
        if vote is None or vote.result is None:
            return None
        raw_title = vote.config.get("title") if isinstance(vote.config, dict) else None
        title = (
            resolve_i18n(raw_title, lang, default_lang)
            if isinstance(raw_title, dict)
            else (raw_title if isinstance(raw_title, str) else None)
        ) or "Abstimmung"
        return VoteResult(title=title, result=vote.result)

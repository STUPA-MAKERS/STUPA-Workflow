"""pdf-Service (T-20): Job-Lebenszyklus + Antrags-Dokument-Laden.

Zwei Verantwortungen, bewusst getrennt:

* **API-Seite** (an eine ``AsyncSession`` gebunden): :meth:`create_application_job`
  legt die ``render_job``-Zeile an (``pending``), :meth:`get_job` liest den Status +
  baut bei Erfolg eine kurzlebige, signierte Ergebnis-URL. Der eigentliche Render
  läuft im Worker (202-Pfad).
* **Daten-Laden**: :meth:`load_application_doc` zieht Felder + Werte + Verlauf + ggf.
  Abstimmungsergebnis aus der DB in einen reinen :class:`ApplicationDoc` — den der
  Worker an :mod:`app.modules.pdf.markdown` (DB-frei, unit-getestet) übergibt.

Der Render-Pipeline-Code (pytex → MinIO → Nextcloud) liegt in :mod:`app.modules.pdf.render`,
damit die Infra-Abhängigkeiten nur worker-seitig injiziert werden.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Applicant, Application, StatusEvent
from app.modules.applications.service import _field_from_row
from app.modules.files.storage import ObjectStorage
from app.modules.flow.models import State
from app.modules.forms.models import FormField
from app.modules.pdf.markdown import ApplicationDoc, TimelineItem, VoteResult
from app.modules.pdf.models import JOB_KIND_APPLICATION_PDF, RenderJob
from app.modules.pdf.schemas import JobOut
from app.modules.voting.models import Vote
from app.settings import Settings
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError
from app.shared.i18n import resolve_i18n


class PdfService:
    """DB-gestützte Render-Job-Operationen + Antrags-Dokument-Aufbereitung."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --------------------------------------------------------------- job-lifecycle
    async def create_application_job(
        self, application_id: UUID, *, idempotency_key: str | None = None
    ) -> RenderJob:
        """``render_job`` (pending) für einen Antrag anlegen. 404, wenn der Antrag fehlt.

        Bei gesetztem ``idempotency_key`` (Flow-Action ``exportPdf``) wird ein bereits
        vorhandener Job desselben Keys **wiederverwendet** (kein Doppel-Render)."""
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
        settings: Settings | None = None,
    ) -> JobOut:
        """Job → ``JobOut``; bei ``done`` + Storage eine signierte Ergebnis-URL beilegen."""
        result_url: str | None = None
        if (
            job.status == "done"
            and job.storage_key is not None
            and storage is not None
            and settings is not None
        ):
            result_url = storage.presigned_get_url(
                job.storage_key,
                expires_seconds=settings.pdf_url_ttl_seconds,
                download_name=f"antrag-{job.application_id}.pdf",
            )
        return JobOut(
            id=job.id,
            kind=job.kind or JOB_KIND_APPLICATION_PDF,
            status=job.status,
            applicationId=job.application_id,
            resultUrl=result_url,
            nextcloudPath=job.nextcloud_path,
            error=job.error,
        )

    # ------------------------------------------------------------- document loading
    async def load_application_doc(self, application_id: UUID) -> ApplicationDoc:
        """Antrag + Felder + Werte + Verlauf + ggf. Abstimmungsergebnis → ``ApplicationDoc``."""
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
            cd_variant=gremium.cd_variant if gremium is not None else None,
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
        """Jüngstes abgeschlossenes Voting des Antrags (mit Ergebnis), sonst ``None``."""
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

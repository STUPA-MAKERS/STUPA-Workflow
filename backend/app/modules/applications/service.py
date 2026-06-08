"""Antrags-Service (T-12): Lebenszyklus + Versionierung + Timeline + Kommentare.

Deckt flows §1/§2 und data-model §1/§2 ab:

* :meth:`create` — Antrag anlegen (öffentlich): ``data`` gegen die effektive Form
  validiert, PII getrennt in ``applicant``, ``submission_version`` v1, Initial-State +
  ``status_event``; promoted ``amount`` aus ``data`` synchronisiert.
* :meth:`patch` — ``data`` ändern → **neue** Version + Diff, **nur** wenn der aktuelle
  State ``edit_allowed`` ist (sonst 409). Validierung **vor** dem DB-Schreibzugriff.
* :meth:`timeline` / :meth:`versions` — Status-Verlauf bzw. Versionshistorie + Diff.
* :meth:`list_applications` — gefilterte, gepagte Liste (Principal-only).
* :meth:`add_comment` / :meth:`list_comments` — interne/öffentliche Kommentare (RBAC).
* :meth:`anonymize` — PII leeren (Mail/Name → NULL, ``anonymized_at``), Antrag bleibt;
  PII-markierte ``data``-Felder werden mit-geleert (data-model §1, R14.3).

Form-/Topf-Felder kommen aus T-11: laufende Anträge validieren gegen ihre **gepinnte**
``form_version`` (data-model §4), nicht gegen die aktuell aktive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType
from app.modules.applications.diff import DataDiff, compute_diff, is_empty_diff
from app.modules.applications.models import (
    Applicant,
    Application,
    Comment,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.applications.schemas import (
    ApplicantOut,
    ApplicationCreate,
    ApplicationListItem,
    ApplicationOut,
    CommentOut,
    StateOut,
    TimelineEventOut,
    VersionOut,
)
from app.modules.budget.models import BudgetField
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.service import FormsService
from app.modules.forms.validation import (
    AnswerValidationError,
    extract_promoted,
    validate_answers,
)
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from app.shared.paging import Page

# Promoted-Ziel, das in `application.amount` (numeric) synchronisiert wird.
_AMOUNT_TARGET = "amount"


def _field_from_row(row: Any) -> FormFieldDef:  # noqa: ANN401 — form_field-Zeile
    """``form_field``-Zeile → ``FormFieldDef`` (camelCase-Input wie in forms.service)."""
    return FormFieldDef.model_validate(
        {
            "key": row.key,
            "type": row.type,
            "label": row.label_i18n,
            "help": row.help_i18n,
            "required": row.required,
            "validation": row.validation or None,
            "visibleIf": row.visible_if,
            "compute": row.compute,
            "options": row.options,
            "isPII": row.is_pii,
            "isPromoted": row.is_promoted,
            "promoteTarget": row.promote_target,
        }
    )


def _state_out(state: State | None) -> StateOut | None:
    if state is None:
        return None
    return StateOut(
        id=state.id,
        key=state.key,
        label=state.label_i18n,
        category=state.category,
        editAllowed=state.edit_allowed,
        kind=state.kind,
    )


def _whitelist(fields: list[FormFieldDef], data: dict[str, Any]) -> dict[str, Any]:
    """``data`` strikt auf die bekannten Feld-Keys der effektiven Form reduzieren.

    Unbekannte Keys werden **verworfen** (nicht persistiert): der öffentliche POST darf
    sonst beliebige, GIN-indizierte Junk-Blobs ablegen (DoS-/Amplification-Fläche)."""
    known = {f.key for f in fields}
    return {k: v for k, v in data.items() if k in known}


def _scrub_diff(diff: dict[str, Any], pii_keys: set[str]) -> dict[str, Any]:
    """PII-Feld-Keys aus einem gespeicherten ``DataDiff`` entfernen (added/removed/changed).

    Diff-Werte enthalten alte/neue Klartext-Feldwerte → beim Anonymisieren mit-leeren."""
    return {
        bucket: {k: v for k, v in (entries or {}).items() if k not in pii_keys}
        for bucket, entries in diff.items()
    }


def _amount_currency(
    fields: list[FormFieldDef], data: dict[str, Any]
) -> tuple[Decimal | None, str | None]:
    """Promoted ``amount`` aus ``data`` ziehen (data-model §2). Währung default EUR."""
    promoted = extract_promoted(fields, data)
    raw = promoted.get(_AMOUNT_TARGET)
    if raw is None:
        return None, None
    amount = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    return amount, "EUR"


class ApplicationsService:
    """DB-gestützte Antrags-Operationen (an eine ``AsyncSession`` gebunden)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ----------------------------------------------------------------- helpers
    async def _get_app(self, application_id: UUID) -> Application:
        app = await self.session.get(Application, application_id)
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    async def _get_state(self, state_id: UUID | None) -> State | None:
        if state_id is None:
            return None
        return await self.session.get(State, state_id)

    async def _current_version(self, application_id: UUID) -> int:
        version = await self.session.scalar(
            select(func.max(SubmissionVersion.version)).where(
                SubmissionVersion.application_id == application_id
            )
        )
        return version or 0

    async def _pinned_fields(self, app: Application) -> list[FormFieldDef]:
        """Felder der **gepinnten** Form-Version des Antrags (+ Topf-Felder)."""
        from app.modules.forms.models import FormField

        rows = (
            await self.session.scalars(
                select(FormField)
                .where(FormField.form_version_id == app.form_version_id)
                .order_by(FormField.order)
            )
        ).all()
        fields = [_field_from_row(r) for r in rows]
        if app.budget_pot_id is not None:
            pot_rows = (
                await self.session.scalars(
                    select(BudgetField)
                    .where(BudgetField.budget_pot_id == app.budget_pot_id)
                    .order_by(BudgetField.order)
                )
            ).all()
            fields.extend(FormFieldDef.model_validate(r.field) for r in pot_rows)
        return fields

    async def _to_out(
        self, app: Application, *, include_pii: bool
    ) -> ApplicationOut:
        state = await self._get_state(app.current_state_id)
        version = await self._current_version(app.id)
        applicant_out: ApplicantOut | None = None
        if include_pii:
            applicant = (
                await self.session.execute(
                    select(Applicant).where(Applicant.application_id == app.id)
                )
            ).scalar_one_or_none()
            if applicant is not None:
                applicant_out = ApplicantOut(
                    email=applicant.email,
                    name=applicant.name,
                    anonymized=applicant.anonymized_at is not None,
                )
        return ApplicationOut(
            id=app.id,
            typeId=app.type_id,
            state=_state_out(state),
            gremiumId=app.gremium_id,
            budgetPotId=app.budget_pot_id,
            amount=app.amount,
            currency=app.currency,
            data=app.data,
            version=version,
            lang=app.lang,
            createdAt=app.created_at,
            updatedAt=app.updated_at,
            applicant=applicant_out,
        )

    # ------------------------------------------------------------------ create
    async def create(self, payload: ApplicationCreate) -> tuple[Application, str]:
        """Antrag anlegen. Rückgabe = (Antrag, applicant_email) für den Mail-Versand.

        Reihenfolge (flows §1): effektive Form laden → ``validate_answers`` (422 vor
        DB) → Antrag + PII + v1 + Initial-State + ``status_event``."""
        app_type = await self.session.get(ApplicationType, payload.type_id)
        if app_type is None:
            raise NotFoundError(f"application type {payload.type_id} not found")
        # Global-Flow-Redesign (#28): bevorzugt den aktiven GLOBALEN Flow
        # (application_type_id IS NULL). Existiert keiner, fällt der per-Typ-Flow
        # als Übergangslösung ein (Cutover). Fehlt beides → 404.
        flow_version_id = await self._resolve_flow_version_id(app_type)

        # Effektive Form (Typ + ggf. Topf-Felder); validiert Topf-Scoping (404).
        forms = FormsService(self.session)
        effective = await forms.get_effective_form(
            payload.type_id, payload.budget_pot_id
        )
        fields = [f for section in effective.sections for f in section.fields]

        context = {"has_budget": app_type.has_budget}
        try:
            validate_answers(fields, payload.data, context)
        except AnswerValidationError as exc:
            raise ValidationProblem(
                "Invalid application data.",
                errors=[{"field": e.field, "msg": e.msg} for e in exc.errors],
            ) from exc

        initial = await self._initial_state(flow_version_id)
        # Nur bekannte Feld-Keys persistieren (unbekannte verwerfen, HIGH #1).
        clean = _whitelist(fields, payload.data)
        amount, currency = _amount_currency(fields, clean)

        app = Application(
            type_id=payload.type_id,
            form_version_id=effective.form_version_id,
            flow_version_id=flow_version_id,
            current_state_id=initial.id,
            gremium_id=app_type.gremium_id,
            budget_pot_id=payload.budget_pot_id,
            amount=amount,
            currency=currency,
            data=clean,
            lang=payload.lang,
        )
        self.session.add(app)
        await self.session.flush()

        self.session.add(
            Applicant(
                application_id=app.id,
                email=str(payload.applicant_email),
                name=payload.applicant_name,
            )
        )
        self.session.add(
            SubmissionVersion(
                application_id=app.id,
                version=1,
                data=clean,
                changed_by="applicant",
                diff=None,
            )
        )
        self.session.add(
            StatusEvent(
                application_id=app.id,
                from_state_id=None,
                to_state_id=initial.id,
                actor="applicant",
            )
        )
        await self.session.commit()
        return app, str(payload.applicant_email)

    async def _resolve_flow_version_id(self, app_type: ApplicationType) -> UUID:
        """Aktiven Flow für einen neuen Antrag bestimmen (#28).

        Bevorzugt den **globalen** Flow (``application_type_id IS NULL`` & ``active``);
        sonst der per-Typ-Flow (``active_flow_version_id``, Übergangslösung). Fehlt
        beides → 404."""
        global_flow_id = (
            await self.session.execute(
                select(FlowVersion.id).where(
                    FlowVersion.application_type_id.is_(None),
                    FlowVersion.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if global_flow_id is not None:
            return global_flow_id
        if app_type.active_flow_version_id is not None:
            return app_type.active_flow_version_id
        raise NotFoundError(
            f"no active flow (global or per-type) for application type {app_type.id}"
        )

    async def _initial_state(self, flow_version_id: UUID) -> State:
        state = (
            await self.session.execute(
                select(State).where(
                    State.flow_version_id == flow_version_id,
                    State.is_initial.is_(True),
                )
            )
        ).scalar_one_or_none()
        if state is None:
            raise NotFoundError("flow has no initial state")
        return state

    # ------------------------------------------------------------------- read
    async def get(self, application_id: UUID, *, include_pii: bool) -> ApplicationOut:
        app = await self._get_app(application_id)
        return await self._to_out(app, include_pii=include_pii)

    # ------------------------------------------------------------------ patch
    async def patch(
        self, application_id: UUID, data: dict[str, Any], *, changed_by: str
    ) -> ApplicationOut:
        """``data`` aktualisieren → neue Version + Diff. Gesperrter State → 409."""
        app = await self._get_app(application_id)
        state = await self._get_state(app.current_state_id)
        if state is not None and not state.edit_allowed:
            raise ConflictError("Application is locked for editing in its current state.")

        # Validierung VOR dem Schreibzugriff (422 statt 500), gegen die gepinnte Form.
        fields = await self._pinned_fields(app)
        # `has_budget`-Kontext aus dem Typ (wie bei create) — NICHT aus budget_pot_id:
        # sonst flippt `visibleIf: has_budget` bei einem has_budget-Typ ohne Topf und
        # ein Pflichtfeld ließe sich beim Edit straflos entfernen (MED).
        app_type = await self.session.get(ApplicationType, app.type_id)
        clean = _whitelist(fields, data)
        context = {"has_budget": app_type.has_budget if app_type is not None else False}
        try:
            validate_answers(fields, clean, context)
        except AnswerValidationError as exc:
            raise ValidationProblem(
                "Invalid application data.",
                errors=[{"field": e.field, "msg": e.msg} for e in exc.errors],
            ) from exc

        diff: DataDiff = compute_diff(app.data, clean)
        next_version = await self._current_version(application_id) + 1
        self.session.add(
            SubmissionVersion(
                application_id=app.id,
                version=next_version,
                data=clean,
                changed_by=changed_by,
                diff=None if is_empty_diff(diff) else dict(diff),
            )
        )
        app.data = clean
        app.amount, app.currency = _amount_currency(fields, clean)
        await self.session.commit()
        # `updated_at` (server-seitiges onupdate) ist nach dem UPDATE expired →
        # vor dem Serialisieren explizit nachladen (sonst Lazy-IO außerhalb await).
        await self.session.refresh(app)
        return await self._to_out(app, include_pii=False)

    # --------------------------------------------------------------- timeline
    async def timeline(self, application_id: UUID) -> list[TimelineEventOut]:
        await self._get_app(application_id)
        events = (
            await self.session.scalars(
                select(StatusEvent)
                .where(StatusEvent.application_id == application_id)
                .order_by(StatusEvent.at)
            )
        ).all()
        out: list[TimelineEventOut] = []
        for ev in events:
            to_state = await self._get_state(ev.to_state_id)
            out.append(
                TimelineEventOut(
                    fromStateId=ev.from_state_id,
                    toStateId=ev.to_state_id,
                    toState=_state_out(to_state),
                    actor=ev.actor,
                    at=ev.at,
                    note=ev.note,
                )
            )
        return out

    # --------------------------------------------------------------- versions
    async def versions(self, application_id: UUID) -> list[VersionOut]:
        await self._get_app(application_id)
        rows = (
            await self.session.scalars(
                select(SubmissionVersion)
                .where(SubmissionVersion.application_id == application_id)
                .order_by(SubmissionVersion.version)
            )
        ).all()
        return [
            VersionOut(
                version=r.version,
                data=r.data,
                diff=r.diff,  # type: ignore[arg-type] — gespeicherter DataDiff
                changedBy=r.changed_by,
                at=r.at,
            )
            for r in rows
        ]

    # ------------------------------------------------------------------- list
    async def list_applications(
        self,
        *,
        state_id: UUID | None = None,
        gremium_id: UUID | None = None,
        type_id: UUID | None = None,
        budget_pot_id: UUID | None = None,
        q: str | None = None,
        limit: int,
        offset: int,
    ) -> Page[ApplicationListItem]:
        """Gefilterte, gepagte Antragsliste (api.md ``GET /applications``)."""
        filters = []
        if state_id is not None:
            filters.append(Application.current_state_id == state_id)
        if gremium_id is not None:
            filters.append(Application.gremium_id == gremium_id)
        if type_id is not None:
            filters.append(Application.type_id == type_id)
        if budget_pot_id is not None:
            filters.append(Application.budget_pot_id == budget_pot_id)
        if q:
            filters.append(cast(Application.data, Text).ilike(f"%{q}%"))

        total = await self.session.scalar(
            select(func.count()).select_from(Application).where(*filters)
        )
        rows = (
            await self.session.scalars(
                select(Application)
                .where(*filters)
                .order_by(Application.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        items: list[ApplicationListItem] = []
        for app in rows:
            state = await self._get_state(app.current_state_id)
            items.append(
                ApplicationListItem(
                    id=app.id,
                    typeId=app.type_id,
                    state=_state_out(state),
                    gremiumId=app.gremium_id,
                    budgetPotId=app.budget_pot_id,
                    amount=app.amount,
                    currency=app.currency,
                    createdAt=app.created_at,
                    updatedAt=app.updated_at,
                )
            )
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    # --------------------------------------------------------------- comments
    async def add_comment(
        self,
        application_id: UUID,
        *,
        author: str | None,
        author_kind: str,
        body: str,
        visibility: str,
    ) -> CommentOut:
        await self._get_app(application_id)
        comment = Comment(
            application_id=application_id,
            author=author,
            author_kind=author_kind,
            body=body,
            visibility=visibility,
        )
        self.session.add(comment)
        await self.session.commit()
        return CommentOut(
            id=comment.id,
            author=comment.author,
            authorKind=author_kind,  # type: ignore[arg-type] — gegen CHECK validiert
            body=comment.body,
            visibility=visibility,  # type: ignore[arg-type]
            at=comment.at,
        )

    async def list_comments(
        self, application_id: UUID, *, include_internal: bool
    ) -> list[CommentOut]:
        await self._get_app(application_id)
        stmt = select(Comment).where(Comment.application_id == application_id)
        if not include_internal:
            stmt = stmt.where(Comment.visibility == "public")
        rows = (await self.session.scalars(stmt.order_by(Comment.at))).all()
        return [
            CommentOut(
                id=c.id,
                author=c.author,
                authorKind=c.author_kind,  # type: ignore[arg-type]
                body=c.body,
                visibility=c.visibility,  # type: ignore[arg-type]
                at=c.at,
            )
            for c in rows
        ]

    # ------------------------------------------------------------- anonymize
    async def anonymize(self, application_id: UUID) -> None:
        """PII leeren (Mail/Name → NULL, ``anonymized_at`` setzen), Antrag bleibt.

        Zusätzlich werden ``isPII``-markierte ``data``-Felder geleert (data-model §1)."""
        app = await self._get_app(application_id)
        applicant = (
            await self.session.execute(
                select(Applicant).where(Applicant.application_id == application_id)
            )
        ).scalar_one_or_none()
        if applicant is not None:
            applicant.email = None
            applicant.name = None
            applicant.anonymized_at = datetime.now(UTC)

        fields = await self._pinned_fields(app)
        pii_keys = {f.key for f in fields if f.is_pii}
        if pii_keys:
            app.data = {k: v for k, v in app.data.items() if k not in pii_keys}
            # PII steckt auch in jeder gespeicherten Version + deren Diff (DSGVO Art. 17):
            # alle submission_version-Zeilen mit-scrubben, sonst leakt versions()/Timeline
            # den alten Klartext-Snapshot (HIGH #2).
            versions = (
                await self.session.scalars(
                    select(SubmissionVersion).where(
                        SubmissionVersion.application_id == application_id
                    )
                )
            ).all()
            for v in versions:
                v.data = {k: val for k, val in v.data.items() if k not in pii_keys}
                if v.diff is not None:
                    v.diff = _scrub_diff(v.diff, pii_keys)
        await self.session.commit()
        # onupdate-Spalten nach dem UPDATE expired → nachladen (vermeidet Lazy-IO).
        await self.session.refresh(app)

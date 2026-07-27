"""Versioned data edits: patch with diff, version history, deletion."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.admin.models import ApplicationType
from app.modules.applications.diff import DataDiff, compute_diff, is_empty_diff
from app.modules.applications.models import SubmissionVersion
from app.modules.applications.schemas import ApplicationOut, VersionOut
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    _amount_currency,
    _whitelist,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.forms.validation import (
    SYSTEM_TITLE_KEY,
    AnswerValidationError,
    system_title_field,
    validate_answers,
)
from app.shared.errors import ConflictError, ValidationProblem


class EditOps(ApplicationsServiceBase):
    """Versioned ``data`` edits, version history and deletion."""

    async def patch(
        self,
        application_id: UUID,
        data: dict[str, Any],
        *,
        changed_by: str,
        bypass_state_lock: bool = False,
        allow_unconfirmed: bool = True,
    ) -> ApplicationOut:
        """Update ``data`` and write a new version with a diff.

        A locked state raises 409, unless ``bypass_state_lock`` is true. The
        caller sets that flag when it holds ``application.edit_any``.
        """
        app = await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        state = await self._get_state(app.current_state_id)
        if state is not None and not state.edit_allowed and not bypass_state_lock:
            raise ConflictError("Application is locked for editing in its current state.")

        # Validate against the pinned form before the write, to answer 422 not 500.
        fields = await self._pinned_fields(app)
        # Prepend the system title field, as ``effective_form`` does. The pinned
        # rows lack the ``title`` field that the runtime adds. Without this step
        # ``_whitelist`` drops the title on every PATCH and loses data.
        if not any(f.key == SYSTEM_TITLE_KEY for f in fields):
            fields = [system_title_field(), *fields]
        # Take the ``has_budget`` context from the type, as create does. Do not
        # take it from ``budget_pot_id``. Otherwise ``visibleIf: has_budget``
        # flips for a has_budget type without a pot, and an edit could drop a
        # required field without a penalty.
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
        try:
            await self.session.commit()
        except IntegrityError as exc:
            # A concurrent PATCH wrote the same version number and broke the
            # unique index on (application_id, version). Answer 409 instead of
            # 500. The client then retries.
            await self.session.rollback()
            raise ConflictError(
                "Concurrent update detected; please retry.", code="conflict"
            ) from exc
        # The UPDATE expires ``updated_at``, a server-side onupdate column. Reload
        # it before serializing, to avoid lazy IO outside an await.
        await self.session.refresh(app)
        return await self._to_out(app, include_pii=False)

    async def delete(self, application_id: UUID, *, actor: str | None) -> None:
        """Delete an application and cascade to the dependent rows.

        The cascade covers the PII, the versions, the events and the budget rows.
        The delete is irreversible, so the method audits it. It writes an
        ``APPLICATION_DELETE`` entry in the same transaction before the delete.
        That entry holds id references and metadata only, never raw PII.
        """
        app = await self._get_app(application_id)
        version_count = await self.session.scalar(
            select(func.count())
            .select_from(SubmissionVersion)
            .where(SubmissionVersion.application_id == application_id)
        )
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.APPLICATION_DELETE,
            target_type="application",
            target_id=str(app.id),
            data={
                "typeId": str(app.type_id),
                "gremiumId": str(app.gremium_id) if app.gremium_id else None,
                "currentStateId": (
                    str(app.current_state_id) if app.current_state_id else None
                ),
                "fiscalYearId": (
                    str(app.fiscal_year_id) if app.fiscal_year_id else None
                ),
                "budgetId": str(app.budget_id) if app.budget_id else None,
                "versionCount": int(version_count or 0),
            },
        )
        await self.session.delete(app)
        await self.session.commit()

    async def versions(
        self, application_id: UUID, *, allow_unconfirmed: bool = True
    ) -> list[VersionOut]:
        await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        rows = (
            await self.session.scalars(
                select(SubmissionVersion)
                .where(SubmissionVersion.application_id == application_id)
                .order_by(SubmissionVersion.version)
            )
        ).all()
        # Resolve the editor sub to a display name. The UI never shows a raw UUID.
        names = await self._author_names({r.changed_by for r in rows if r.changed_by})
        return [
            VersionOut(
                version=r.version,
                data=r.data,
                diff=r.diff,  # type: ignore[arg-type] — stored DataDiff
                changedBy=(names.get(r.changed_by, r.changed_by) if r.changed_by else None),
                at=r.at,
            )
            for r in rows
        ]

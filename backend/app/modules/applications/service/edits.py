"""Versioned data edits: patch with diff, version history, deletion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.modules.admin.models import ApplicationType
from app.modules.applications.diff import DataDiff, compute_diff, is_empty_diff
from app.modules.applications.models import MagicLink, SubmissionVersion
from app.modules.applications.schemas import ApplicationOut, VersionOut
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    _amount_currency,
    _scrub_diff,
    _whitelist,
    _without_keys,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.deadlines.service import state_deadline_follows_edits
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
        preserve_pii: bool = False,
    ) -> ApplicationOut:
        """Update ``data`` and write a new version with a diff.

        A locked state raises 409, unless ``bypass_state_lock`` is true. The
        caller sets that flag when it holds ``application.edit_any``.

        ``preserve_pii`` is for an editor without the PII right (O21). That editor
        read ``data`` without the ``isPII`` fields, so the patch keeps the stored
        values of these fields and ignores the sent ones. A validation error on an
        ``isPII`` field does not stop that patch, because the editor cannot fix it.
        The response then also holds no ``isPII`` field.

        The edit writes an ``application_update`` audit entry with the version
        number and the keys of the changed fields, never the values. When the
        deadline policy of the current state is ``relative_changed``, the
        deadline moves to the new ``updated_at``.
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
        # ``has_budget`` comes from the type, as it does on create.
        app_type = await self.session.get(ApplicationType, app.type_id)
        pii_keys: set[str] = set()
        if preserve_pii:
            pii_keys = await self._pii_keys_for_type(app.type_id)
            stored = app.data or {}
            data = {
                **_without_keys(data, pii_keys),
                **{k: v for k, v in stored.items() if k in pii_keys},
            }
        clean = _whitelist(fields, data)
        context = {"has_budget": app_type.has_budget if app_type is not None else False}
        try:
            validate_answers(fields, clean, context)
        except AnswerValidationError as exc:
            # The editor without the PII right can neither see nor change an
            # ``isPII`` field. A stored value that is missing or no longer valid
            # (the field became required or PII later, or anonymization removed
            # it) is therefore not an error of this edit.
            errors = [e for e in exc.errors if e.field not in pii_keys]
            if errors:
                raise ValidationProblem(
                    "Invalid application data.",
                    errors=[{"field": e.field, "msg": e.msg} for e in errors],
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
        # Keys only: a field value can hold PII.
        await audit_record(
            self.session,
            actor=changed_by,
            action=AuditAction.APPLICATION_UPDATE,
            target_type="application",
            target_id=str(app.id),
            data={
                "version": next_version,
                "changedFields": sorted(
                    {*diff["added"], *diff["removed"], *diff["changed"]}
                ),
            },
        )
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
        if state is not None and await state_deadline_follows_edits(
            self.session, state.config
        ):
            # Local import: the flow engine imports the applications models.
            from app.modules.flow.service import FlowService

            await FlowService(self.session).schedule_state_deadline(app, state)
        return await self._to_out(app, include_pii=False, strip_pii_fields=preserve_pii)

    async def set_archived(
        self,
        application_id: UUID,
        *,
        archived: bool,
        actor: str | None,
        strip_pii_fields: bool = False,
    ) -> ApplicationOut:
        """Move an application out of the working list, or bring it back.

        Archiving is orthogonal to the flow: it can happen in any state, because the flow
        records where a decision stands and this records whether anyone still needs to
        look. It is also NOT anonymization — nothing is hidden and nothing is deleted, and
        `be-privacy` owns the DSGVO erasure that people will confuse this with.

        A plain column change writes no timeline entry and no audit entry by itself, which
        a flow transition would have done for free. Both directions are therefore recorded
        explicitly. The entry carries id references and the direction, never raw PII.

        Setting the state it already has is a no-op rather than an error: two clicks on
        the same row should not fail, and re-archiving must not overwrite who archived it
        first.

        Archiving also expires every magic link of the application (Z1). A link can
        live without an expiry, so the archive is one of the events that end it.
        Bringing the application back does not revive the links. Archiving ends the
        existing links only, not the access: an archived application stays readable,
        so the applicant can still request a new link to the same mailbox, with or
        without the application being brought back.
        """
        app = await self._get_app(application_id)
        already = app.archived_at is not None
        if already == archived:
            return await self._to_out(app, include_pii=False, strip_pii_fields=strip_pii_fields)

        await audit_record(
            self.session,
            actor=actor,
            action=(
                AuditAction.APPLICATION_ARCHIVE
                if archived
                else AuditAction.APPLICATION_UNARCHIVE
            ),
            target_type="application",
            target_id=str(app.id),
            data={
                "typeId": str(app.type_id),
                "gremiumId": str(app.gremium_id) if app.gremium_id else None,
                "currentStateId": (
                    str(app.current_state_id) if app.current_state_id else None
                ),
            },
        )
        now = datetime.now(UTC)
        if archived:
            await self.session.execute(
                update(MagicLink)
                .where(
                    MagicLink.application_id == app.id,
                    or_(MagicLink.expires_at.is_(None), MagicLink.expires_at > now),
                )
                .values(expires_at=now)
            )
        app.archived_at = now if archived else None
        app.archived_by = actor if archived else None
        await self.session.commit()
        await self.session.refresh(app)
        return await self._to_out(app, include_pii=False, strip_pii_fields=strip_pii_fields)

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
        self,
        application_id: UUID,
        *,
        allow_unconfirmed: bool = True,
        applicant_view: bool = False,
        magic_link_view: bool = False,
        strip_pii: bool = False,
    ) -> list[VersionOut]:
        """Return the version history, oldest version first.

        A full reader gets ``data``, ``diff`` and ``changedKeys``. With
        ``strip_pii`` the ``isPII`` fields leave all three (O21). The
        ``applicant_view`` gets the metadata only (A11, O17): number, time and
        changed keys, no values. Its ``changedBy`` names the Gremium for every edit
        that the applicant did not do (A12). ``magic_link_view`` marks the
        magic-link reader; see `_applicant_actors`.
        """
        app = await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        rows = (
            await self.session.scalars(
                select(SubmissionVersion)
                .where(SubmissionVersion.application_id == application_id)
                .order_by(SubmissionVersion.version)
            )
        ).all()
        hidden = await self._pii_keys_for_type(app.type_id) if strip_pii else set()
        # Resolve every editor in one batch. The UI never shows a raw sub or key.
        actors = await self._resolve_actors(
            app,
            (r.changed_by for r in rows),
            applicant_view=applicant_view,
            magic_link_view=magic_link_view,
        )
        out: list[VersionOut] = []
        for r in rows:
            diff = _scrub_diff(r.diff, hidden) if r.diff else None
            changed = sorted(
                {k for bucket in (diff or {}).values() for k in (bucket or {})}
            )
            info = actors.get(r.changed_by) if r.changed_by else None
            out.append(
                VersionOut(
                    version=r.version,
                    data=None if applicant_view else _without_keys(r.data, hidden),
                    diff=None if applicant_view else diff,  # type: ignore[arg-type] — stored DataDiff
                    changedKeys=changed,
                    changedBy=info.legacy(r.changed_by) if info and r.changed_by else None,
                    changedByInfo=info,
                    at=r.at,
                )
            )
        return out

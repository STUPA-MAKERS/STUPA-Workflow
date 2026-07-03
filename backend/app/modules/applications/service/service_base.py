"""Shared base of the :class:`~.service.ApplicationsService` ops classes.

Constructor plus the lookup/serialization helpers used by several concerns
(create, edits, reads, listing, comments, anonymization), and the pure
module-level field/data helpers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select

from app.modules.applications.models import Applicant, Application, SubmissionVersion
from app.modules.applications.schemas import ApplicantOut, ApplicationOut, StateOut
from app.modules.budget.models import BudgetField
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.validation import extract_promoted
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Promoted target synchronized into ``application.amount`` (numeric).
_AMOUNT_TARGET = "amount"


def _field_from_row(row: Any) -> FormFieldDef:  # noqa: ANN401 — form_field row
    """``form_field`` row → ``FormFieldDef`` (camelCase input, as in forms.service)."""
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


def _title_of(data: dict[str, Any] | None) -> str | None:
    """Application title from the data (system ``title`` field), for list views."""
    if not data:
        return None
    value = data.get("title")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _state_out(state: State | None, color_override: str | None = None) -> StateOut | None:
    if state is None:
        return None
    return StateOut(
        id=state.id,
        key=state.key,
        label=state.label_i18n,
        # Existing applications point at old state rows (color=NULL) after the global
        # flow was re-saved; the color is resolved from the active global flow (same
        # state key), with the stored row as fallback.
        color=color_override if color_override is not None else state.color,
        editAllowed=state.edit_allowed,
        kind=state.kind,
    )


def _whitelist(fields: list[FormFieldDef], data: dict[str, Any]) -> dict[str, Any]:
    """Strictly reduce ``data`` to the known field keys of the effective form.

    Unknown keys are discarded (not persisted): the public POST could otherwise
    store arbitrary GIN-indexed junk blobs (DoS/amplification surface)."""
    known = {f.key for f in fields}
    return {k: v for k, v in data.items() if k in known}


def _scrub_diff(diff: dict[str, Any], pii_keys: set[str]) -> dict[str, Any]:
    """Drop PII field keys from a stored ``DataDiff`` (added/removed/changed).

    Diff values carry old/new plaintext field values → blanked on anonymization."""
    return {
        bucket: {k: v for k, v in (entries or {}).items() if k not in pii_keys}
        for bucket, entries in diff.items()
    }


def _amount_currency(
    fields: list[FormFieldDef], data: dict[str, Any]
) -> tuple[Decimal | None, str | None]:
    """Extract the promoted ``amount`` from ``data``; currency defaults to EUR."""
    promoted = extract_promoted(fields, data)
    raw = promoted.get(_AMOUNT_TARGET)
    if raw is None:
        return None, None
    amount = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    return amount, "EUR"


class ApplicationsServiceBase:
    """DB-backed application operations (bound to one session) — shared base."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_app(
        self, application_id: UUID, *, allow_unconfirmed: bool = True
    ) -> Application:
        app = await self.session.get(Application, application_id)
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        # Unconfirmed guest submissions stay invisible until magic-link confirmation.
        # Principal/committee item routes pass allow_unconfirmed=False and get 404
        # (not 403) to avoid an existence oracle; the owning applicant (magic link)
        # reads with the default.
        if not allow_unconfirmed and app.email_confirmed_at is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    async def _get_state(self, state_id: UUID | None) -> State | None:
        if state_id is None:
            return None
        return await self.session.get(State, state_id)

    async def _resolve_state_colors(self) -> dict[str, str | None]:
        """``{state_key: color}`` from the active global flow, cached per instance.

        Re-saving the global flow creates a NEW FlowVersion with NEW state rows;
        existing applications keep pointing at old rows (``color=NULL``). Colors are
        therefore resolved by state key against the active flow, with the stored
        ``state.color`` as fallback (see :func:`_state_out`)."""
        cached = getattr(self, "_state_color_map", None)
        if cached is not None:
            return cached
        rows = (
            await self.session.execute(
                select(State.key, State.color)
                .join(FlowVersion, FlowVersion.id == State.flow_version_id)
                .where(FlowVersion.active.is_(True))
            )
        ).all()
        color_map: dict[str, str | None] = {key: color for key, color in rows if color is not None}
        self._state_color_map: dict[str, str | None] = color_map
        return color_map

    async def _state_out_resolved(self, state: State | None) -> StateOut | None:
        """:func:`_state_out` with the color resolved from the active global flow."""
        if state is None:
            return None
        colors = await self._resolve_state_colors()
        return _state_out(state, colors.get(state.key))

    async def _current_version(self, application_id: UUID) -> int:
        version = await self.session.scalar(
            select(func.max(SubmissionVersion.version)).where(
                SubmissionVersion.application_id == application_id
            )
        )
        return version or 0

    async def _pinned_fields(self, app: Application) -> list[FormFieldDef]:
        """Fields of the application's **pinned** form version (+ pot fields)."""
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

    async def _pii_keys_for_type(self, type_id: UUID) -> set[str]:
        """``isPII`` field keys across ALL form versions of a type (for anonymization).

        An application is pinned to its ``form_version_id``; a field marked PII only
        in a later version is unknown to the pinned row. GDPR erasure follows the
        current intent — hence the union."""
        from app.modules.forms.models import FormField, FormVersion

        rows = await self.session.scalars(
            select(FormField.key)
            .join(FormVersion, FormVersion.id == FormField.form_version_id)
            .where(
                FormVersion.application_type_id == type_id,
                FormField.is_pii.is_(True),
            )
        )
        return set(rows)

    async def _to_out(
        self,
        app: Application,
        *,
        include_pii: bool,
        can_edit: bool = False,
        is_owner: bool = False,
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
            state=await self._state_out_resolved(state),
            gremiumId=app.gremium_id,
            budgetPotId=app.budget_pot_id,
            budgetId=app.budget_id,
            fiscalYearId=app.fiscal_year_id,
            amount=app.amount,
            currency=app.currency,
            data=app.data,
            version=version,
            lang=app.lang,
            createdAt=app.created_at,
            updatedAt=app.updated_at,
            applicant=applicant_out,
            canEdit=can_edit,
            isOwner=is_owner,
        )

    async def _author_names(self, subs: set[str]) -> dict[str, str]:
        """Author ``principal.sub`` → display name (display_name/email/sub)."""
        from app.modules.auth.models import Principal as PrincipalRow

        wanted = {s for s in subs if s}
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(PrincipalRow.sub, PrincipalRow.display_name, PrincipalRow.email).where(
                    PrincipalRow.sub.in_(wanted)
                )
            )
        ).all()
        return {sub: (dn or em or sub) for sub, dn, em in rows}

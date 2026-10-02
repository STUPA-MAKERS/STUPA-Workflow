"""Shared base of the `service.ApplicationsService` ops classes.

This module holds the constructor and the lookup and serialization helpers that
several concerns share: create, edits, reads, listing, comments and anonymization. It
also holds the pure module-level field and data helpers.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Subquery, func, select

from app.modules.applications.models import (
    Applicant,
    Application,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.applications.schemas import ApplicantOut, ApplicationOut, StateOut
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.validation import extract_promoted
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Promoted target that the service synchronizes into the numeric `application.amount`.
_AMOUNT_TARGET = "amount"


def _field_from_row(row: Any) -> FormFieldDef:  # noqa: ANN401 — form_field row
    """Convert a `form_field` row to a `FormFieldDef`.

    The mapping uses camelCase input keys, as `forms.service` does.
    """
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
    """Read the application title from the `title` system field, for the list views."""
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
        # After a re-save of the global flow, an existing application points at an old
        # state row with color=NULL. The color therefore comes from the active global
        # flow through the same state key, with the stored row as fallback.
        color=color_override if color_override is not None else state.color,
        editAllowed=state.edit_allowed,
        kind=state.kind,
    )


def state_since_subquery() -> Subquery:
    """Build the grouped subquery ``(app_id, since)`` of the last status change (A9).

    ``since`` is the time of the newest ``status_event`` of each application. The
    creation writes the first event, so every application has one. A caller joins
    the subquery with an outer join and falls back to ``created_at``.
    """
    return (
        select(
            StatusEvent.application_id.label("app_id"),
            func.max(StatusEvent.at).label("since"),
        )
        .group_by(StatusEvent.application_id)
        .subquery("state_since")
    )


# Actor value of a magic-link applicant in `status_event`, `submission_version` and
# the audit log.
APPLICANT_ACTOR = "applicant"


def applicant_actors(created_by: str | None) -> set[str]:
    """Return the actor values that name the applicant of one application.

    These are the magic-link actor and the ``sub`` of the logged-in creator. The
    applicant view keeps these actors and shows the Gremium for all others (A12).
    """
    return {APPLICANT_ACTOR} | ({created_by} if created_by else set())


def _without_keys(data: dict[str, Any] | None, keys: set[str]) -> dict[str, Any]:
    """Return a copy of ``data`` without ``keys``."""
    return {k: v for k, v in (data or {}).items() if k not in keys}


def _whitelist(fields: list[FormFieldDef], data: dict[str, Any]) -> dict[str, Any]:
    """Reduce `data` strictly to the known field keys of the effective form.

    The function drops an unknown key, so the database never stores it. Without this
    rule the public POST could store any junk blob in a GIN-indexed column. That is a
    denial-of-service and amplification surface.
    """
    known = {f.key for f in fields}
    return {k: v for k, v in data.items() if k in known}


def _scrub_diff(diff: dict[str, Any], pii_keys: set[str]) -> dict[str, Any]:
    """Drop the PII field keys from a stored `DataDiff`.

    The function covers the added, removed and changed buckets. A diff value carries
    the old and the new plaintext field value, so anonymization must blank it.
    """
    return {
        bucket: {k: v for k, v in (entries or {}).items() if k not in pii_keys}
        for bucket, entries in diff.items()
    }


def _amount_currency(
    fields: list[FormFieldDef], data: dict[str, Any]
) -> tuple[Decimal | None, str | None]:
    """Extract the promoted `amount` from `data`.

    The currency defaults to EUR.
    """
    promoted = extract_promoted(fields, data)
    raw = promoted.get(_AMOUNT_TARGET)
    if raw is None:
        return None, None
    amount = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    return amount, "EUR"


class ApplicationsServiceBase:
    """Shared base for the DB-backed application operations, bound to one session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_app(
        self, application_id: UUID, *, allow_unconfirmed: bool = True
    ) -> Application:
        app = await self.session.get(Application, application_id)
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        # An unconfirmed guest submission stays invisible until the magic link confirms
        # it. The principal and Gremium item routes pass allow_unconfirmed=False and get
        # 404 instead of 403, which prevents an existence oracle. The owning applicant
        # reads through the magic link with the default.
        if not allow_unconfirmed and app.email_confirmed_at is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    async def _get_state(self, state_id: UUID | None) -> State | None:
        if state_id is None:
            return None
        return await self.session.get(State, state_id)

    async def _resolve_state_colors(self) -> dict[str, str | None]:
        """Map each state key to its color from the active global flow.

        The result is cached per instance. A re-save of the global flow creates a new
        FlowVersion with new state rows. An existing application keeps a pointer to an
        old row, where the color is NULL. The service therefore resolves the color by
        state key against the active flow, with the stored `state.color` as fallback.
        See `_state_out`.
        """
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
        """Call `_state_out` with the color resolved from the active global flow."""
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
        """Return the fields of the pinned form version plus the budget-pot fields."""
        from app.modules.forms.models import FormField

        rows = (
            await self.session.scalars(
                select(FormField)
                .where(FormField.form_version_id == app.form_version_id)
                .order_by(FormField.order)
            )
        ).all()
        return [_field_from_row(r) for r in rows]

    async def _pii_keys_for_type(self, type_id: UUID) -> set[str]:
        """Collect the `isPII` field keys across all form versions of a type.

        Anonymization uses this set. An application is pinned to its `form_version_id`.
        A field that only a later version marks as PII is unknown to the pinned row.
        GDPR erasure follows the current intent, so the function takes the union.
        """
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

    async def _state_since_map(self, app_ids: Iterable[UUID]) -> dict[UUID, datetime]:
        """Map each application id to the time of its last status change (A9).

        One grouped query for all ids. An id without a status event is missing from
        the map; the caller falls back to ``created_at``.
        """
        ids = set(app_ids)
        if not ids:
            return {}
        sq = state_since_subquery()
        rows = (
            await self.session.execute(select(sq.c.app_id, sq.c.since).where(sq.c.app_id.in_(ids)))
        ).all()
        return {app_id: since for app_id, since in rows}

    async def _strip_pii_fields(
        self, type_id: UUID, data: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Remove the ``isPII`` fields from ``data`` for a reader without the PII right (O21).

        The key set is the union over every form version of the type, as for the
        anonymization. A field that a later version marks as PII stays hidden too.
        """
        return _without_keys(data, await self._pii_keys_for_type(type_id))

    async def _gremium_actor(self, app: Application) -> str | None:
        """Return the name of the Gremium of the application.

        The applicant view shows this name instead of a member name (A12, O16).
        Without a Gremium the result is None, so no member name leaks either.
        """
        if app.gremium_id is None:
            return None
        from app.modules.admin.models import Gremium

        return await self.session.scalar(select(Gremium.name).where(Gremium.id == app.gremium_id))

    async def _to_out(
        self,
        app: Application,
        *,
        include_pii: bool,
        can_edit: bool = False,
        is_owner: bool = False,
        strip_pii_fields: bool = False,
    ) -> ApplicationOut:
        """Serialize one application.

        ``include_pii`` adds the applicant block (email, name). ``strip_pii_fields``
        removes the ``isPII`` form fields from ``data`` (O21).
        """
        state = await self._get_state(app.current_state_id)
        version = await self._current_version(app.id)
        since = (await self._state_since_map([app.id])).get(app.id, app.created_at)
        data = (
            await self._strip_pii_fields(app.type_id, app.data)
            if strip_pii_fields
            else app.data
        )
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
            budgetId=app.budget_id,
            fiscalYearId=app.fiscal_year_id,
            amount=app.amount,
            currency=app.currency,
            data=data,
            version=version,
            lang=app.lang,
            createdAt=app.created_at,
            updatedAt=app.updated_at,
            applicant=applicant_out,
            canEdit=can_edit,
            isOwner=is_owner,
            archivedAt=app.archived_at,
            stateSince=since,
        )

    async def _author_names(self, subs: set[str]) -> dict[str, str]:
        """Map an author `principal.sub` to `display_name`, `email` or the `sub`."""
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

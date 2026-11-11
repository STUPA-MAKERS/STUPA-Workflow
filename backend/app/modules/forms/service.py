"""Forms service: form-version CRUD and the effective form (DB layer).

A version pins the definition. A save creates a new form version and leaves the old
versions unchanged. A running application keeps its ``form_version_id``. A partial unique
index allows at most one ``active`` version per type. On activation the service first
deactivates the other versions. It then updates
``application_type.active_form_version_id``.

The pure validation and merge logic lives in `app.modules.forms.validation`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.application_types.models import ApplicationType
from app.modules.forms.models import FormField, FormVersion
from app.modules.forms.schemas import (
    SECTION_LABELS,
    EffectiveFormOut,
    FormDraftOut,
    FormSectionOut,
)
from app.modules.forms.validation import (
    effective_form,
)
from app.modules.gremien.models import Gremium
from app.shared.config_schemas import FieldOption, FormFieldDef
from app.shared.errors import NotFoundError, ValidationProblem


def _row_to_field_def(row: FormField) -> FormFieldDef:
    """Convert a ``form_field`` row into a ``FormFieldDef`` (camelCase input)."""
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


#: The read of the cost-center options of a `budget_select` field.
BudgetOptions = Callable[[AsyncSession], Awaitable[list[FieldOption]]]

#: Field types whose options the server injects at render time, not the form builder.
DYNAMIC_OPTION_TYPES: frozenset[str] = frozenset({"gremium_select", "budget_select"})


def _inject_dynamic_options(
    fields: Sequence[FormFieldDef], options_by_type: Mapping[str, list[FieldOption]]
) -> tuple[FormFieldDef, ...]:
    """Set the server-side options on the dynamic picker fields.

    ``options_by_type`` maps a field type to its options. ``gremium_select`` gets the
    Gremien, ``budget_select`` gets the budget tree. The function keeps every other field
    as it is. It copies only the affected fields, because ``FormFieldDef`` is immutable.
    """
    return tuple(
        f.model_copy(update={"options": options_by_type[f.type]})
        if f.type in options_by_type
        else f
        for f in fields
    )


def field_def_to_row_kwargs(field: FormFieldDef, order: int) -> dict[str, Any]:
    """Convert a ``FormFieldDef`` into the kwargs of a ``form_field`` row."""
    return {
        "key": field.key,
        "type": field.type,
        "label_i18n": field.label,
        "help_i18n": field.help,
        "required": field.required,
        "validation": (
            field.validation.model_dump(by_alias=True, exclude_none=True)
            if field.validation is not None
            else {}
        ),
        "visible_if": field.visible_if,
        "compute": field.compute,
        "options": (
            [o.model_dump(by_alias=True, exclude_none=True) for o in field.options]
            if field.options is not None
            else None
        ),
        "order": order,
        "is_pii": field.is_pii,
        "is_promoted": field.is_promoted,
        "promote_target": field.promote_target,
    }


@dataclass(frozen=True)
class FormsService:
    """DB-backed form operations, bound to one ``AsyncSession``.

    ``budget_options`` reads the options of a ``budget_select`` field. The module
    `budget` owns this read (`budget.form_options`), and a caller passes it in, because
    `forms` imports no higher module (§S/backend/python/000651).
    """

    session: AsyncSession
    budget_options: BudgetOptions | None = None

    async def _get_type(self, type_id: UUID) -> ApplicationType:
        app_type = await self.session.get(ApplicationType, type_id)
        if app_type is None:
            raise NotFoundError(f"application type {type_id} not found")
        return app_type

    async def _fields_of_version(self, form_version_id: UUID) -> tuple[FormFieldDef, ...]:
        rows = (
            await self.session.scalars(
                select(FormField)
                .where(FormField.form_version_id == form_version_id)
                .order_by(FormField.order)
            )
        ).all()
        return tuple(_row_to_field_def(r) for r in rows)

    async def get_effective_form(
        self,
        type_id: UUID,
        *,
        form_version_id: UUID | None = None,
    ) -> EffectiveFormOut:
        """Return the effective form definition.

        ``form_version_id`` overrides the active version. A running application uses this
        to render and edit its pinned form instead of the changed active one.

        The server injects the options of the dynamic picker fields only here. Each type costs
        one lookup, and only when the form holds such a field. A marker section carries its own
        label. ``main`` and ``budget`` use the default labels.
        """
        app_type = await self._get_type(type_id)
        version_id = form_version_id or app_type.active_form_version_id
        if version_id is None:
            raise NotFoundError(f"application type {type_id} has no active form version")

        type_fields = await self._fields_of_version(version_id)
        sections = effective_form(type_fields)

        present = {f.type for s in sections for f in s.fields} & DYNAMIC_OPTION_TYPES
        gremium_options = (
            await self._gremium_field_options() if "gremium_select" in present else None
        )
        budget_options = await self._budget_field_options() if "budget_select" in present else None
        options_by_type = {
            field_type: options
            for field_type, options in (
                ("gremium_select", gremium_options),
                ("budget_select", budget_options),
            )
            if options is not None
        }

        return EffectiveFormOut(
            applicationTypeId=type_id,
            formVersionId=version_id,
            hasBudget=app_type.has_budget,
            sections=tuple(
                FormSectionOut(
                    key=s.key,
                    label=s.label or SECTION_LABELS.get(s.key) or SECTION_LABELS["main"],
                    fields=_inject_dynamic_options(s.fields, options_by_type),
                )
                for s in sections
            ),
        )

    async def _budget_field_options(self) -> list[FieldOption]:
        """Return the options of a `budget_select` field from the wired source.

        Raises:
            RuntimeError: The caller wired no source. A form with a cost-center field
                must never render without its options.
        """
        if self.budget_options is None:
            raise RuntimeError("The cost-center options of the form are not wired.")
        return await self.budget_options(self.session)

    async def _gremium_field_options(self) -> list[FieldOption]:
        """Return the current Gremien as `select` options for `gremium_select`.

        The stored answer value is the UUID of the Gremium. The label is the name in both
        languages, because a Gremium name has no i18n split.
        """
        rows = (
            await self.session.execute(select(Gremium.id, Gremium.name).order_by(Gremium.name))
        ).all()
        return [
            FieldOption(value=str(gid), label={"de": name, "en": name}) for gid, name in rows
        ]

    async def set_form_active(self, type_id: UUID, active: bool) -> FormDraftOut:
        """Activate or deactivate the form of an application type.

        ``active=False`` sets ``active_form_version_id`` to ``NULL``. The type is then
        locked for new applications. A running application keeps its pinned version.
        ``active=True`` reactivates the latest version.

        Raises:
            ValidationProblem: The type has no form version to activate.
        """
        app_type = await self._get_type(type_id)
        await self.session.execute(
            update(FormVersion)
            .where(
                FormVersion.application_type_id == type_id,
                FormVersion.active.is_(True),
            )
            .values(active=False)
        )
        if active:
            latest = await self.session.scalar(
                select(FormVersion)
                .where(FormVersion.application_type_id == type_id)
                .order_by(FormVersion.version.desc())
                .limit(1)
            )
            if latest is None:
                raise ValidationProblem(
                    "No form version to activate.",
                    errors=[{"field": "active", "msg": "no form version exists"}],
                )
            latest.active = True
            app_type.active_form_version_id = latest.id
        else:
            app_type.active_form_version_id = None
        await self.session.commit()
        return await self.get_form_draft(type_id)

    async def get_form_draft(self, type_id: UUID) -> FormDraftOut:
        """Return the most recent form version of an application type for editing.

        The result holds the raw field list and the description. It has no pot merge and
        no sections. That is the job of the public ``get_effective_form`` path. If the
        type has no version yet, the service returns an empty definition and the editor
        starts empty.
        """
        await self._get_type(type_id)
        version = await self.session.scalar(
            select(FormVersion)
            .where(FormVersion.application_type_id == type_id)
            .order_by(FormVersion.version.desc())
            .limit(1)
        )
        if version is None:
            return FormDraftOut(applicationTypeId=type_id, fields=[])
        fields = await self._fields_of_version(version.id)
        return FormDraftOut(
            applicationTypeId=type_id,
            formVersionId=version.id,
            version=version.version,
            active=version.active,
            description=version.description_i18n,
            fields=list(fields),
        )

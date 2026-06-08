"""Forms-Service (T-11): Form-Version-CRUD + effektive Form (DB-Schicht).

Versionierung pinnt: eine neue Form-Version wird **angelegt**, alte Versionen
bleiben unverändert — laufende Anträge behalten ihre ``form_version_id`` (data-model
§4 »Versionierte Configs«). Max. eine ``active`` Version je Typ (partial-unique):
beim Aktivieren werden andere zuerst deaktiviert, dann
``application_type.active_form_version_id`` umgesetzt.

Die reine Validierungs-/Merge-Logik liegt in :mod:`app.modules.forms.validation`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType
from app.modules.budget.models import BudgetField, BudgetPot
from app.modules.forms.models import FormField, FormVersion
from app.modules.forms.schemas import (
    SECTION_LABELS,
    EffectiveFormOut,
    FormDraftOut,
    FormSectionOut,
    FormVersionCreate,
    FormVersionOut,
)
from app.modules.forms.validation import (
    FormDefinitionError,
    effective_form,
    validate_definition,
)
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError, ValidationProblem


def _row_to_field_def(row: FormField) -> FormFieldDef:
    """DB-``form_field``-Zeile → ``FormFieldDef`` (camelCase-Input)."""
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


def _field_def_to_row_kwargs(field: FormFieldDef, order: int) -> dict[str, Any]:
    """``FormFieldDef`` → kwargs für eine ``form_field``-Zeile."""
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
            [o.model_dump(by_alias=True) for o in field.options]
            if field.options is not None
            else None
        ),
        "order": order,
        "is_pii": field.is_pii,
        "is_promoted": field.is_promoted,
        "promote_target": field.promote_target,
    }


class FormsService:
    """DB-gestützte Form-Operationen (an eine ``AsyncSession`` gebunden)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_type(self, type_id: UUID) -> ApplicationType:
        app_type = await self.session.get(ApplicationType, type_id)
        if app_type is None:
            raise NotFoundError(f"application type {type_id} not found")
        return app_type

    async def _fields_of_version(self, form_version_id: UUID) -> list[FormFieldDef]:
        rows = (
            await self.session.scalars(
                select(FormField)
                .where(FormField.form_version_id == form_version_id)
                .order_by(FormField.order)
            )
        ).all()
        return [_row_to_field_def(r) for r in rows]

    async def _pot_fields(
        self, app_type: ApplicationType, budget_pot_id: UUID
    ) -> list[FormFieldDef]:
        """Topf-Extra-Felder laden — nur für einen Topf, der zum Typ-Gremium gehört.

        Verhindert Cross-Gremium-Leak (N1): ein fremder/typ-fremder Topf darf nicht
        an die öffentliche effektive Form gehängt werden. Nicht-passende Töpfe →
        404 (keine Existenz preisgeben).
        """
        pot = await self.session.get(BudgetPot, budget_pot_id)
        if pot is None:
            raise NotFoundError(f"budget pot {budget_pot_id} not found")
        if not app_type.has_budget:
            raise NotFoundError(
                f"application type {app_type.id} does not support budget pots"
            )
        if app_type.gremium_id is None or pot.gremium_id != app_type.gremium_id:
            raise NotFoundError(
                f"budget pot {budget_pot_id} is not available for this application type"
            )
        rows = (
            await self.session.scalars(
                select(BudgetField)
                .where(BudgetField.budget_pot_id == budget_pot_id)
                .order_by(BudgetField.order)
            )
        ).all()
        return [FormFieldDef.model_validate(r.field) for r in rows]

    async def get_effective_form(
        self, type_id: UUID, budget_pot_id: UUID | None = None
    ) -> EffectiveFormOut:
        """Effektive Form-Definition liefern (api.md ``/application-types/{id}/form``)."""
        app_type = await self._get_type(type_id)
        if app_type.active_form_version_id is None:
            raise NotFoundError(f"application type {type_id} has no active form version")

        type_fields = await self._fields_of_version(app_type.active_form_version_id)
        pot_fields = (
            await self._pot_fields(app_type, budget_pot_id) if budget_pot_id else None
        )
        sections = effective_form(type_fields, pot_fields)

        return EffectiveFormOut(
            applicationTypeId=type_id,
            formVersionId=app_type.active_form_version_id,
            budgetPotId=budget_pot_id,
            sections=[
                FormSectionOut(key=s.key, label=SECTION_LABELS[s.key], fields=s.fields)
                for s in sections
            ],
        )

    async def create_form_version(
        self, type_id: UUID, payload: FormVersionCreate
    ) -> FormVersionOut:
        """Neue Form-Version anlegen (Definition validiert; optional aktivieren)."""
        # Eingabe vor DB-Zugriff prüfen: defekte Definition → 422 (statt 500), api.md §2.
        try:
            validate_definition(payload.fields)
        except FormDefinitionError as exc:
            raise ValidationProblem(
                "Invalid form definition.", errors=[{"field": "fields", "msg": str(exc)}]
            ) from exc
        await self._get_type(type_id)

        next_version = await self._next_version(type_id)

        version = FormVersion(
            application_type_id=type_id,
            version=next_version,
            active=payload.activate,
            description_i18n=payload.description,
        )
        if payload.activate:
            await self.session.execute(
                update(FormVersion)
                .where(
                    FormVersion.application_type_id == type_id,
                    FormVersion.active.is_(True),
                )
                .values(active=False)
            )
        self.session.add(version)
        await self.session.flush()

        for order, field in enumerate(payload.fields):
            self.session.add(
                FormField(form_version_id=version.id, **_field_def_to_row_kwargs(field, order))
            )

        if payload.activate:
            app_type = await self._get_type(type_id)
            app_type.active_form_version_id = version.id

        await self.session.commit()
        return FormVersionOut(
            id=version.id,
            applicationTypeId=type_id,
            version=next_version,
            active=payload.activate,
            fields=list(payload.fields),
            description=payload.description,
        )

    async def get_form_draft(self, type_id: UUID) -> FormDraftOut:
        """Zuletzt angelegte Form-Version eines Typs zum Bearbeiten (#13).

        Rohe Feld-Liste + Beschreibung — ohne Topf-Merge/Sektionen (das ist der
        öffentliche ``get_effective_form``-Pfad). Hat der Typ noch keine Version,
        kommt eine leere Definition (Editor startet leer).
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
            fields=fields,
        )

    async def _next_version(self, type_id: UUID) -> int:
        current_max = await self.session.scalar(
            select(FormVersion.version)
            .where(FormVersion.application_type_id == type_id)
            .order_by(FormVersion.version.desc())
            .limit(1)
        )
        return (current_max or 0) + 1

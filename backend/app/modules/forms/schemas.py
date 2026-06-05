"""API-Schemata des Forms-Moduls (T-11).

Request/Response-Modelle für Form-Version-CRUD und die effektive Form-Definition
(`GET /api/application-types/{id}/form`). Feld-Definitionen sind ``FormFieldDef``
(config_schemas §5.1, Single Source of Truth) — hier nur die Hüllen-Schemata.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.config_schemas import FormFieldDef
from app.shared.i18n import I18nMap

# i18n-Labels der Standard-Sektionen (effective_form §5.7).
SECTION_LABELS: dict[str, I18nMap] = {
    "main": {"de": "Antrag", "en": "Application"},
    "budget": {"de": "Topf-spezifische Felder", "en": "Budget-specific fields"},
}


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class FormVersionCreate(_CamelModel):
    """Neue Form-Version anlegen (Definition wird validiert)."""

    fields: list[FormFieldDef] = Field(min_length=1)
    activate: bool = True


class FormVersionOut(_CamelModel):
    """Angelegte/aktive Form-Version."""

    id: UUID
    application_type_id: UUID = Field(alias="applicationTypeId")
    version: int
    active: bool
    fields: list[FormFieldDef]


class FormSectionOut(_CamelModel):
    """Ein Abschnitt der effektiven Form."""

    key: str
    label: I18nMap
    fields: list[FormFieldDef]


class EffectiveFormOut(_CamelModel):
    """Effektive Form-Definition (Typ-Felder + ggf. Topf-Extra-Felder)."""

    application_type_id: UUID = Field(alias="applicationTypeId")
    form_version_id: UUID = Field(alias="formVersionId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    sections: list[FormSectionOut]

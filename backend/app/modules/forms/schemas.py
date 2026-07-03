"""API schemas of the forms module.

Request/response models for form-version CRUD and the effective form definition
(`GET /api/application-types/{id}/form`). Field definitions are ``FormFieldDef`` (the
single source of truth) — only the wrapper schemas live here.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.config_schemas import FormFieldDef
from app.shared.i18n import I18nMap

# i18n labels of the standard sections.
SECTION_LABELS: dict[str, I18nMap] = {
    "main": {"de": "Antrag", "en": "Application"},
    "budget": {"de": "Topf-spezifische Felder", "en": "Budget-specific fields"},
}


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields populatable by name."""

    model_config = ConfigDict(populate_by_name=True)


class FormVersionCreate(_CamelModel):
    """Create a new form version (definition validated)."""

    fields: list[FormFieldDef] = Field(min_length=1)
    activate: bool = True
    # Form description (multilingual Markdown), optional.
    description: I18nMap | None = None


class FormActiveSet(_CamelModel):
    """Activate/deactivate a type's form.

    ``active=false`` ⇒ the type has no active form version (locked for new
    applications); ``active=true`` reactivates the latest version.
    """

    active: bool


class FormVersionOut(_CamelModel):
    """Created/active form version."""

    id: UUID
    application_type_id: UUID = Field(alias="applicationTypeId")
    version: int
    active: bool
    fields: list[FormFieldDef]
    description: I18nMap | None = None


class FormDraftOut(_CamelModel):
    """A type's current (most recent) form version for editing.

    Returns the raw field list + description (no pot merge/sections) for the form
    editor. ``formVersionId``/``version`` are ``null`` when the type has no form version
    yet (freshly created) → the editor starts empty.
    """

    application_type_id: UUID = Field(alias="applicationTypeId")
    form_version_id: UUID | None = Field(default=None, alias="formVersionId")
    version: int | None = None
    active: bool = False
    description: I18nMap | None = None
    fields: list[FormFieldDef]


class FormSectionOut(_CamelModel):
    """A section of the effective form."""

    key: str
    label: I18nMap
    fields: list[FormFieldDef]


class EffectiveFormOut(_CamelModel):
    """Effective form definition (type fields + optional pot extra fields)."""

    application_type_id: UUID = Field(alias="applicationTypeId")
    form_version_id: UUID = Field(alias="formVersionId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    sections: list[FormSectionOut]

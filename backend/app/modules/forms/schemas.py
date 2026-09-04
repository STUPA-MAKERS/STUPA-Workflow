"""API schemas of the forms module.

The module holds the request and response models for form-version CRUD and for the
effective form definition (`GET /api/application-types/{id}/form`). ``FormFieldDef`` stays
the single source of truth for a field definition. Only the wrapper schemas live here.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.config_schemas import FormFieldDef
from app.shared.i18n import I18nMap

SECTION_LABELS: dict[str, I18nMap] = {
    "main": {"de": "Antrag", "en": "Application"},
    "budget": {"de": "Topf-spezifische Felder", "en": "Budget-specific fields"},
}


class _CamelModel(BaseModel):
    """Base model that uses camelCase aliases in JSON.

    The model also accepts the Python field names as input.
    """

    model_config = ConfigDict(populate_by_name=True)


class FormVersionCreate(_CamelModel):
    """Request body for a new form version.

    The server validates the field definition.
    """

    fields: list[FormFieldDef] = Field(min_length=1)
    activate: bool = True
    # Multilingual Markdown description of the form.
    description: I18nMap | None = None


class FormActiveSet(_CamelModel):
    """Activate or deactivate the form of an application type.

    With ``active=false`` the type has no active form version. It is then locked for new
    applications. With ``active=true`` the latest version becomes active again.
    """

    active: bool


class FormVersionOut(_CamelModel):
    """The created or activated form version."""

    id: UUID
    application_type_id: UUID = Field(alias="applicationTypeId")
    version: int
    active: bool
    fields: list[FormFieldDef]
    description: I18nMap | None = None


class FormDraftOut(_CamelModel):
    """The most recent form version of an application type, for the form editor.

    The payload holds the raw field list and the description. It has no pot merge and no
    sections. ``formVersionId`` and ``version`` are ``null`` when the type has no form
    version yet. The editor then starts empty.
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
    """Effective form definition for one application type."""

    application_type_id: UUID = Field(alias="applicationTypeId")
    form_version_id: UUID = Field(alias="formVersionId")
    # The client evaluates ``visibleIf: has_budget`` against this. It belongs to the
    # type; deriving it anywhere else disagrees with the server's own validation.
    has_budget: bool = Field(default=False, alias="hasBudget")
    sections: list[FormSectionOut]

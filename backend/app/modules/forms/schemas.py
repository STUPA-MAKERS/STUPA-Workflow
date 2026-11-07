"""API schemas of the forms module.

The module holds the request and response models for form-version CRUD and for the
effective form definition (`GET /api/application-types/{id}/form`). ``FormFieldDef`` stays
the single source of truth for a field definition. Only the wrapper schemas live here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import Field

from app.shared.config_schemas import FormFieldDef
from app.shared.i18n import I18nMap
from app.shared.schemas import FrozenCamelModel

SECTION_LABELS: Mapping[str, I18nMap] = {
    "main": {"de": "Antrag", "en": "Application"},
    "budget": {"de": "Topf-spezifische Felder", "en": "Budget-specific fields"},
}


class FormVersionCreate(FrozenCamelModel, frozen=True):
    """Request body for a new form version.

    The server validates the field definition.
    """

    fields: Sequence[FormFieldDef] = Field(min_length=1)
    activate: bool = True
    #: Multilingual Markdown description of the form.
    description: I18nMap | None = None


class FormActiveSet(FrozenCamelModel, frozen=True):
    """Activate or deactivate the form of an application type.

    With ``active=false`` the type has no active form version. It is then locked for new
    applications. With ``active=true`` the latest version becomes active again.
    """

    active: bool


class FormVersionOut(FrozenCamelModel, frozen=True):
    """The created or activated form version."""

    id: UUID
    application_type_id: UUID = Field(alias="applicationTypeId")
    version: int
    active: bool
    fields: Sequence[FormFieldDef]
    description: I18nMap | None = None


class FormDraftOut(FrozenCamelModel, frozen=True):
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
    fields: Sequence[FormFieldDef]


class FormSectionOut(FrozenCamelModel, frozen=True):
    """A section of the effective form."""

    key: str
    label: I18nMap
    fields: Sequence[FormFieldDef]


class EffectiveFormOut(FrozenCamelModel, frozen=True):
    """Effective form definition for one application type.

    Attributes:
        has_budget: The client evaluates ``visibleIf: has_budget`` against this value. It
            belongs to the type, because a value derived anywhere else disagrees with the
            validation of the server.
    """

    application_type_id: UUID = Field(alias="applicationTypeId")
    form_version_id: UUID = Field(alias="formVersionId")
    has_budget: bool = Field(default=False, alias="hasBudget")
    sections: Sequence[FormSectionOut]

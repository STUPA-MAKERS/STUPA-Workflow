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
    # NC-Forms-Beschreibung (mehrsprachiges Markdown), optional (#13).
    description: I18nMap | None = None


class FormActiveSet(_CamelModel):
    """Formular eines Typs aktivieren/deaktivieren (#forms).

    ``active=false`` ⇒ Typ hat keine aktive Form-Version mehr (für neue Anträge
    gesperrt); ``active=true`` reaktiviert die **neueste** Version.
    """

    active: bool


class FormVersionOut(_CamelModel):
    """Angelegte/aktive Form-Version."""

    id: UUID
    application_type_id: UUID = Field(alias="applicationTypeId")
    version: int
    active: bool
    fields: list[FormFieldDef]
    description: I18nMap | None = None


class FormDraftOut(_CamelModel):
    """Aktuelle (zuletzt angelegte) Form-Version eines Typs zum Bearbeiten (#13).

    Liefert die rohe Feld-Liste + Beschreibung (ohne Topf-Merge/Sektionen) für den
    NC-Forms-Editor. ``formVersionId``/``version`` sind ``null``, wenn der Typ noch
    keine Form-Version hat (frisch angelegt) → Editor startet leer.
    """

    application_type_id: UUID = Field(alias="applicationTypeId")
    form_version_id: UUID | None = Field(default=None, alias="formVersionId")
    version: int | None = None
    active: bool = False
    description: I18nMap | None = None
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

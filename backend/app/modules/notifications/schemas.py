"""API-Schemata des Notifications-Moduls (T-18, api.md §6 / data-model §5.4).

Request/Response für `notification_rule`- und `mail_template`-CRUD + Mail-Vorschau.
camelCase im JSON (per-Name befüllbar). Event-/Empfänger-Validierung passiert hier
(422 vor DB-Zugriff); i18n-Maps sind frei strukturierte Dicts (`{lang: text}`).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.notifications.events import EVENT_SET
from app.shared.i18n import I18nMap

RecipientKind = Literal["group", "role", "applicant"]


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class RecipientSpec(_CamelModel):
    """Ein Empfänger-Eintrag (Gruppe/Rolle/Antragsteller)."""

    kind: RecipientKind
    ref: str | None = None

    @model_validator(mode="after")
    def _ref_required_for_group_role(self) -> RecipientSpec:
        if self.kind in ("group", "role") and not self.ref:
            raise ValueError(f"recipient kind {self.kind!r} requires 'ref'")
        return self


class NotificationRuleCreate(_CamelModel):
    """Neue Benachrichtigungsregel."""

    event: str
    recipients: list[RecipientSpec] = Field(default_factory=list)
    template_key: str = Field(alias="templateKey", min_length=1)
    application_type_id: UUID | None = Field(default=None, alias="applicationTypeId")
    enabled: bool = True

    @field_validator("event")
    @classmethod
    def _known_event(cls, v: str) -> str:
        if v not in EVENT_SET:
            raise ValueError(f"unknown event: {v!r}")
        return v


class NotificationRuleUpdate(_CamelModel):
    """Teil-Update einer Regel (PATCH; nur gesetzte Felder ändern)."""

    event: str | None = None
    recipients: list[RecipientSpec] | None = None
    template_key: str | None = Field(default=None, alias="templateKey")
    application_type_id: UUID | None = Field(default=None, alias="applicationTypeId")
    enabled: bool | None = None

    @field_validator("event")
    @classmethod
    def _known_event(cls, v: str | None) -> str | None:
        if v is not None and v not in EVENT_SET:
            raise ValueError(f"unknown event: {v!r}")
        return v


class NotificationRuleOut(_CamelModel):
    """Persistierte Regel."""

    id: UUID
    event: str
    recipients: list[RecipientSpec]
    template_key: str = Field(serialization_alias="templateKey")
    application_type_id: UUID | None = Field(serialization_alias="applicationTypeId")
    enabled: bool


class MailTemplateCreate(_CamelModel):
    """Neues Mail-Template."""

    key: str = Field(min_length=1)
    subject_i18n: I18nMap = Field(alias="subjectI18n")
    body_i18n: I18nMap = Field(alias="bodyI18n")
    body_html_i18n: I18nMap = Field(default_factory=dict, alias="bodyHtmlI18n")
    placeholders: dict[str, str] = Field(default_factory=dict)


class MailTemplateUpdate(_CamelModel):
    """Teil-Update eines Templates (Key bleibt unveränderlich)."""

    subject_i18n: I18nMap | None = Field(default=None, alias="subjectI18n")
    body_i18n: I18nMap | None = Field(default=None, alias="bodyI18n")
    body_html_i18n: I18nMap | None = Field(default=None, alias="bodyHtmlI18n")
    placeholders: dict[str, str] | None = None


class MailTemplateOut(_CamelModel):
    """Persistiertes Template."""

    id: UUID
    key: str
    subject_i18n: I18nMap = Field(serialization_alias="subjectI18n")
    body_i18n: I18nMap = Field(serialization_alias="bodyI18n")
    body_html_i18n: I18nMap = Field(serialization_alias="bodyHtmlI18n")
    placeholders: dict[str, str]


class MailPreviewRequest(_CamelModel):
    """Vorschau-Anfrage: Template mit Beispiel-Kontext + Sprache rendern."""

    lang: str = "de"
    context: dict[str, object] = Field(default_factory=dict)


class MailPreviewOut(_CamelModel):
    """Gerenderte Vorschau."""

    subject: str
    text: str
    html: str | None = None
    lang: str

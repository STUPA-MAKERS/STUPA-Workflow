"""API-Schemata des Notifications-Moduls (T-18, data-model §5.4).

Request/Response für `mail_template`-CRUD + Mail-Vorschau. camelCase im JSON
(per-Name befüllbar); i18n-Maps sind frei strukturierte Dicts (`{lang: text}`).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.i18n import I18nMap


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


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


class NotificationPreferenceOut(_CamelModel):
    """Effektiver Schalter einer Benachrichtigungs-Art (#4-2)."""

    kind: str
    enabled: bool


class NotificationPreferencesUpdate(_CamelModel):
    """Bulk-Update der eigenen Benachrichtigungs-Schalter."""

    preferences: list[NotificationPreferenceOut]


class NotificationSettingsOut(_CamelModel):
    """Plattformweite Benachrichtigungs-Config (#task-reminder, Single-Row)."""

    task_reminder_enabled: bool = Field(alias="taskReminderEnabled")
    task_reminder_after_days: int = Field(alias="taskReminderAfterDays", ge=1)
    # 0 = nur einmal je State-Aufenthalt erinnern.
    task_reminder_repeat_days: int = Field(alias="taskReminderRepeatDays", ge=0)


class NotificationSettingsUpdate(_CamelModel):
    """Teil-Update der Plattform-Config (nur gesetzte Felder ändern)."""

    task_reminder_enabled: bool | None = Field(
        default=None, alias="taskReminderEnabled"
    )
    task_reminder_after_days: int | None = Field(
        default=None, alias="taskReminderAfterDays", ge=1
    )
    task_reminder_repeat_days: int | None = Field(
        default=None, alias="taskReminderRepeatDays", ge=0
    )

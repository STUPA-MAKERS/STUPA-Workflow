"""API schemas of the notifications module.

Request/response for ``mail_template`` CRUD and mail preview. JSON is camelCase
(populate-by-name); i18n maps are free-form ``{lang: text}`` dicts.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.i18n import I18nMap


class _CamelModel(BaseModel):
    """camelCase JSON aliases; fields populatable by name."""

    model_config = ConfigDict(populate_by_name=True)


class MailTemplateCreate(_CamelModel):
    """A new mail template."""

    key: str = Field(min_length=1)
    subject_i18n: I18nMap = Field(alias="subjectI18n")
    body_i18n: I18nMap = Field(alias="bodyI18n")
    body_html_i18n: I18nMap = Field(default_factory=dict, alias="bodyHtmlI18n")
    placeholders: dict[str, str] = Field(default_factory=dict)


class MailTemplateUpdate(_CamelModel):
    """Partial update of a template (key stays immutable)."""

    subject_i18n: I18nMap | None = Field(default=None, alias="subjectI18n")
    body_i18n: I18nMap | None = Field(default=None, alias="bodyI18n")
    body_html_i18n: I18nMap | None = Field(default=None, alias="bodyHtmlI18n")
    placeholders: dict[str, str] | None = None


class MailTemplateUpsert(_CamelModel):
    """Create/update an override by ``key``.

    The editor saves both builtin (no DB row yet) and override templates the
    same way — keyed by ``key`` rather than id, since builtins have no id.
    """

    key: str = Field(min_length=1)
    subject_i18n: I18nMap = Field(alias="subjectI18n")
    body_i18n: I18nMap = Field(alias="bodyI18n")
    body_html_i18n: I18nMap = Field(default_factory=dict, alias="bodyHtmlI18n")


class MailTemplateOut(_CamelModel):
    """Template as shown in the editor — override (DB) or builtin default."""

    # Builtins (not yet overridden) have no DB id.
    id: UUID | None = None
    key: str
    subject_i18n: I18nMap = Field(serialization_alias="subjectI18n")
    body_i18n: I18nMap = Field(serialization_alias="bodyI18n")
    body_html_i18n: I18nMap = Field(serialization_alias="bodyHtmlI18n")
    placeholders: dict[str, str]
    # 'override' = from the DB; 'builtin' = from the catalogue (unchanged).
    source: Literal["override", "builtin"] = "override"


class MailPreviewRequest(_CamelModel):
    """Preview request: render a template with sample context and language."""

    lang: str = "de"
    context: dict[str, object] = Field(default_factory=dict)


class MailPreviewPayloadRequest(_CamelModel):
    """Preview from an editor draft (no persisted id)."""

    subject_i18n: I18nMap = Field(alias="subjectI18n")
    body_i18n: I18nMap = Field(alias="bodyI18n")
    body_html_i18n: I18nMap = Field(default_factory=dict, alias="bodyHtmlI18n")
    lang: str = "de"
    context: dict[str, object] = Field(default_factory=dict)


class MailPreviewOut(_CamelModel):
    """Rendered preview."""

    subject: str
    text: str
    html: str | None = None
    lang: str


class NotificationPreferenceOut(_CamelModel):
    """Effective switch for one notification kind."""

    kind: str
    enabled: bool


class NotificationPreferencesUpdate(_CamelModel):
    """Bulk update of own notification switches."""

    preferences: list[NotificationPreferenceOut]


class NotificationSettingsOut(_CamelModel):
    """Platform-wide notification config (single row)."""

    task_reminder_enabled: bool = Field(alias="taskReminderEnabled")
    task_reminder_after_days: int = Field(alias="taskReminderAfterDays", ge=1)
    # 0 = remind only once per state visit.
    task_reminder_repeat_days: int = Field(alias="taskReminderRepeatDays", ge=0)


class NotificationSettingsUpdate(_CamelModel):
    """Partial update of the platform config (only set fields change)."""

    task_reminder_enabled: bool | None = Field(
        default=None, alias="taskReminderEnabled"
    )
    task_reminder_after_days: int | None = Field(
        default=None, alias="taskReminderAfterDays", ge=1
    )
    task_reminder_repeat_days: int | None = Field(
        default=None, alias="taskReminderRepeatDays", ge=0
    )

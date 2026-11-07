"""API schemas of the notifications module.

These models carry the request and the response of the ``mail_template`` CRUD endpoints
and of the mail preview. The JSON keys are camelCase and the models also populate by
name. An i18n map is a free-form ``{lang: text}`` dict.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.shared.i18n import I18nMap
from app.shared.schemas import FrozenCamelModel


class MailTemplateCreate(FrozenCamelModel, frozen=True):
    """A new mail template."""

    key: str = Field(min_length=1)
    subject_i18n: I18nMap = Field(alias="subjectI18n")
    body_i18n: I18nMap = Field(alias="bodyI18n")
    body_html_i18n: I18nMap = Field(default_factory=dict, alias="bodyHtmlI18n")
    placeholders: dict[str, str] = Field(default_factory=dict)


class MailTemplateUpdate(FrozenCamelModel, frozen=True):
    """Partial update of a template (key stays immutable)."""

    subject_i18n: I18nMap | None = Field(default=None, alias="subjectI18n")
    body_i18n: I18nMap | None = Field(default=None, alias="bodyI18n")
    body_html_i18n: I18nMap | None = Field(default=None, alias="bodyHtmlI18n")
    placeholders: dict[str, str] | None = None


class MailTemplateUpsert(FrozenCamelModel, frozen=True):
    """Create or update an override by ``key``.

    The editor saves builtin templates and override templates the same way. A builtin
    has no DB row and no id yet, so the key identifies the template.
    """

    key: str = Field(min_length=1)
    subject_i18n: I18nMap = Field(alias="subjectI18n")
    body_i18n: I18nMap = Field(alias="bodyI18n")
    body_html_i18n: I18nMap = Field(default_factory=dict, alias="bodyHtmlI18n")


class MailTemplateOut(FrozenCamelModel, frozen=True):
    """Template as shown in the editor: a DB override or a builtin default.

    Attributes:
        id: DB id; None for a builtin template without an override.
        source: ``override`` comes from the DB, ``builtin`` from the catalog unchanged.
    """

    id: UUID | None = None
    key: str
    subject_i18n: I18nMap = Field(serialization_alias="subjectI18n")
    body_i18n: I18nMap = Field(serialization_alias="bodyI18n")
    body_html_i18n: I18nMap = Field(serialization_alias="bodyHtmlI18n")
    placeholders: dict[str, str]
    source: Literal["override", "builtin"] = "override"


class MailPreviewRequest(FrozenCamelModel, frozen=True):
    """Preview request: render a template with sample context and language."""

    lang: str = "de"
    context: dict[str, object] = Field(default_factory=dict)


class MailPreviewPayloadRequest(FrozenCamelModel, frozen=True):
    """Preview from an editor draft (no persisted id)."""

    subject_i18n: I18nMap = Field(alias="subjectI18n")
    body_i18n: I18nMap = Field(alias="bodyI18n")
    body_html_i18n: I18nMap = Field(default_factory=dict, alias="bodyHtmlI18n")
    lang: str = "de"
    context: dict[str, object] = Field(default_factory=dict)


class MailPreviewOut(FrozenCamelModel, frozen=True):
    """Rendered preview."""

    subject: str
    text: str
    html: str | None = None
    lang: str


class NotificationPreferenceOut(FrozenCamelModel, frozen=True):
    """Effective switch for one notification kind."""

    kind: str
    enabled: bool


class NotificationPreferencesUpdate(FrozenCamelModel, frozen=True):
    """Bulk update of the own notification switches."""

    preferences: tuple[NotificationPreferenceOut, ...]


class NotificationSettingsOut(FrozenCamelModel, frozen=True):
    """Platform-wide notification config (single row).

    Attributes:
        task_reminder_repeat_days: 0 sends one reminder per state visit only.
    """

    task_reminder_enabled: bool = Field(alias="taskReminderEnabled")
    task_reminder_after_days: int = Field(alias="taskReminderAfterDays", ge=1)
    task_reminder_repeat_days: int = Field(alias="taskReminderRepeatDays", ge=0)


class NotificationSettingsUpdate(FrozenCamelModel, frozen=True):
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

"""Central catalogue of *all* notification mail templates.

Every mail the platform sends is listed here by its ``key``, with the builtin
subject/body (the *same* objects the sender uses as fallback) and placeholder
hints. The editor (`/admin/mail-templates`) shows every mail through it: a DB
override wins if present, else the builtin default, so editor and actual send
never drift apart (no seed-copying into the DB).

Imports the builtins from the respective sender modules; only ``task_reminder``
(sent by the worker) and ``deadline_approaching`` (otherwise falling back to
``status_update``) are defined here as single source.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.notifications import action_dispatcher, auto, comments, privacy
from app.modules.notifications import service as _svc

# --- Builtins defined only here (single source) ---
# task_reminder: sent by the worker (``worker/task_reminders.py``), which imports
# these constants from here (no app→worker import).
TASK_REMINDER_SUBJECT: dict[str, str] = {
    "de": "Erinnerung: offene Aufgabe"
    "{% if applicationTitle %} — „{{ applicationTitle }}“{% endif %}",
    "en": "Reminder: open task"
    '{% if applicationTitle %} — "{{ applicationTitle }}"{% endif %}',
}
TASK_REMINDER_BODY: dict[str, str] = {
    "de": "Hallo,\n\nder Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} wartet seit "
    "{{ daysOpen }} Tagen auf eine Aktion"
    "{% if status %} (Status: {{ status }}){% endif %}.\n",
    "en": "Hello,\n\nthe application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} has been '
    "waiting for action for {{ daysOpen }} days"
    "{% if status %} (status: {{ status }}){% endif %}.\n",
}
# deadline_approaching: ``handle_notify_action`` uses this as the builtin
# fallback when no DB override exists.
DEADLINE_APPROACHING_SUBJECT: dict[str, str] = {
    "de": "Frist-Erinnerung"
    "{% if applicationTitle %} — „{{ applicationTitle }}“{% endif %}",
    "en": "Deadline reminder"
    '{% if applicationTitle %} — "{{ applicationTitle }}"{% endif %}',
}
DEADLINE_APPROACHING_BODY: dict[str, str] = {
    "de": "Hallo,\n\neine Frist"
    "{% if applicationTitle %} zum Antrag „{{ applicationTitle }}“{% endif %} "
    "läuft bald ab{% if dueAt %} (fällig: {{ dueAt }}){% endif %}.\n",
    "en": "Hello,\n\na deadline"
    '{% if applicationTitle %} for the application "{{ applicationTitle }}"{% endif %} '
    "is approaching{% if dueAt %} (due: {{ dueAt }}){% endif %}.\n",
}
# status_update_team: committee-facing default for flow `notify` actions without
# an explicit templateKey and non-applicant recipients — the applicant default
# (`status_update`) reads "Your application" and is wrong for the team.
STATUS_UPDATE_TEAM_SUBJECT: dict[str, str] = {
    "de": "Statuswechsel: Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": "Status change: application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
}
STATUS_UPDATE_TEAM_BODY: dict[str, str] = {
    "de": "Hallo,\n\nder Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} ist in einen "
    "neuen Status gewechselt{% if status %}: {{ status }}{% endif %}.\n\n"
    "Ggf. ist eine Aktion oder Abstimmung erforderlich.\n",
    "en": "Hello,\n\nthe application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} moved to a '
    "new state{% if status %}: {{ status }}{% endif %}.\n\n"
    "An action or vote may be required.\n",
}


@dataclass(frozen=True, slots=True)
class MailTemplateSpec:
    """Builtin spec for a mail (send fallback + editor default)."""

    key: str
    kind: str
    subject_i18n: dict[str, str]
    body_i18n: dict[str, str]
    placeholders: dict[str, str]


# Order = display order in the editor.
TEMPLATE_CATALOGUE: tuple[MailTemplateSpec, ...] = (
    MailTemplateSpec(
        "status_update",
        "status_update",
        _svc._BUILTIN_NOTIFY_SUBJECT,  # noqa: SLF001 — shared builtin
        _svc._BUILTIN_NOTIFY_BODY,  # noqa: SLF001
        {
            "applicationTitle": "Titel des Antrags",
            "status": "Neuer Status",
            "applicationId": "ID des Antrags",
        },
    ),
    MailTemplateSpec(
        "status_update_team",
        "status_update",
        STATUS_UPDATE_TEAM_SUBJECT,
        STATUS_UPDATE_TEAM_BODY,
        {
            "applicationTitle": "Titel des Antrags",
            "status": "Neuer Status",
            "applicationId": "ID des Antrags",
        },
    ),
    MailTemplateSpec(
        "task_new",
        "task",
        action_dispatcher._BUILTIN_TASK_SUBJECT,  # noqa: SLF001
        action_dispatcher._BUILTIN_TASK_BODY,  # noqa: SLF001
        {
            "applicationTitle": "Titel des Antrags",
            "status": "Aktueller Status",
            "applicationId": "ID des Antrags",
        },
    ),
    MailTemplateSpec(
        "task_reminder",
        "task_reminder",
        TASK_REMINDER_SUBJECT,
        TASK_REMINDER_BODY,
        {
            "applicationTitle": "Titel des Antrags",
            "status": "Aktueller Status",
            "daysOpen": "Tage ohne Aktion",
            "applicationId": "ID des Antrags",
        },
    ),
    MailTemplateSpec(
        "deadline_approaching",
        "deadline",
        DEADLINE_APPROACHING_SUBJECT,
        DEADLINE_APPROACHING_BODY,
        {
            "applicationTitle": "Titel des Antrags",
            "dueAt": "Fälligkeitszeitpunkt",
            "kind": "Art der Frist",
            "deadlineId": "ID der Frist",
        },
    ),
    MailTemplateSpec(
        "comment_applicant",
        "comment",
        comments._BUILTIN_APPLICANT_SUBJECT,  # noqa: SLF001
        comments._BUILTIN_APPLICANT_BODY,  # noqa: SLF001
        {
            "applicationTitle": "Titel des Antrags",
            "status": "Aktueller Status",
            "comment": "Kommentartext (Auszug)",
            "applicationId": "ID des Antrags",
        },
    ),
    MailTemplateSpec(
        "comment_team",
        "comment",
        comments._BUILTIN_TEAM_SUBJECT,  # noqa: SLF001
        comments._BUILTIN_TEAM_BODY,  # noqa: SLF001
        {
            "applicationTitle": "Titel des Antrags",
            "status": "Aktueller Status",
            "comment": "Kommentartext (Auszug)",
            "applicationId": "ID des Antrags",
        },
    ),
    MailTemplateSpec(
        "meeting_created",
        "meeting",
        auto._BUILTIN_MEETING_SUBJECT,  # noqa: SLF001
        auto._BUILTIN_MEETING_BODY,  # noqa: SLF001
        {
            "meetingTitle": "Titel der Sitzung",
            "meetingDate": "Datum",
            "meetingTime": "Uhrzeit",
            "gremiumName": "Gremium",
            "meetingId": "ID der Sitzung",
        },
    ),
    MailTemplateSpec(
        "role_assigned",
        "role_change",
        auto._BUILTIN_ROLE_ASSIGNED_SUBJECT,  # noqa: SLF001
        auto._BUILTIN_ROLE_ASSIGNED_BODY,  # noqa: SLF001
        {"roleLabel": "Bezeichnung der Rolle", "gremiumName": "Gremium"},
    ),
    MailTemplateSpec(
        "role_revoked",
        "role_change",
        auto._BUILTIN_ROLE_REVOKED_SUBJECT,  # noqa: SLF001
        auto._BUILTIN_ROLE_REVOKED_BODY,  # noqa: SLF001
        {"roleLabel": "Bezeichnung der Rolle", "gremiumName": "Gremium"},
    ),
    MailTemplateSpec(
        "delegation_granted",
        "delegation",
        auto._BUILTIN_DELEGATION_GRANTED_SUBJECT,  # noqa: SLF001
        auto._BUILTIN_DELEGATION_GRANTED_BODY,  # noqa: SLF001
        {"meetingTitle": "Titel der Sitzung", "delegatorName": "Vollmachtgeber:in"},
    ),
    MailTemplateSpec(
        "delegation_revoked",
        "delegation",
        auto._BUILTIN_DELEGATION_REVOKED_SUBJECT,  # noqa: SLF001
        auto._BUILTIN_DELEGATION_REVOKED_BODY,  # noqa: SLF001
        {"meetingTitle": "Titel der Sitzung", "delegatorName": "Vollmachtgeber:in"},
    ),
    MailTemplateSpec(
        "magic_link",
        "magic_link",
        _svc._BUILTIN_MAGIC_LINK_SUBJECT,  # noqa: SLF001
        _svc._BUILTIN_MAGIC_LINK_BODY,  # noqa: SLF001
        {"link": "Anmelde-Link"},
    ),
    MailTemplateSpec(
        "erasure_requested",
        "privacy",
        privacy.ERASURE_REQUESTED_SUBJECT,
        privacy.ERASURE_REQUESTED_BODY,
        {"subjectType": "Art (applicant/principal)", "requestId": "ID des Löschantrags"},
    ),
    MailTemplateSpec(
        "erasure_executed",
        "privacy",
        privacy.ERASURE_EXECUTED_SUBJECT,
        privacy.ERASURE_EXECUTED_BODY,
        {"subjectType": "Art (applicant/principal)", "requestId": "ID des Löschantrags"},
    ),
    MailTemplateSpec(
        "erasure_rejected",
        "privacy",
        privacy.ERASURE_REJECTED_SUBJECT,
        privacy.ERASURE_REJECTED_BODY,
        {"reason": "Ablehnungsgrund", "requestId": "ID des Löschantrags"},
    ),
)

CATALOGUE_BY_KEY: dict[str, MailTemplateSpec] = {s.key: s for s in TEMPLATE_CATALOGUE}

"""Zentraler Katalog **aller** Benachrichtigungs-Mail-Templates (#12).

Jede Mail, die die Plattform versendet, ist hier mit ihrem ``key`` gelistet —
samt Builtin-Betreff/Text (die *gleichen* Objekte, die der Versand als Fallback
nutzt) und Platzhalter-Hinweisen. Der Editor (`/admin/mail-templates`) zeigt
darüber **jede** Mail an: liegt eine DB-Override vor, gewinnt diese, sonst der
Builtin-Default. Damit driften Editor-Anzeige und tatsächlicher Versand nicht
auseinander (kein Seed-Kopieren in die DB).

Importiert die Builtins aus den jeweiligen Versendermodulen; nur ``task_reminder``
(im Worker versendet) und ``deadline_approaching`` (sonst Fallback auf
``status_update``) werden hier als Single Source definiert — der Worker bzw.
``handle_notify_action`` greift darauf zurück.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.notifications import action_dispatcher, auto, comments
from app.modules.notifications import service as _svc

# --- Builtins, die nur hier leben (Single Source) -------------------------- #
# task_reminder: vom Worker (``worker/task_reminders.py``) versendet, der diese
# Konstanten von hier importiert (kein app→worker-Import).
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
# deadline_approaching: ``handle_notify_action`` nutzt dies als Builtin-Fallback,
# wenn keine DB-Override existiert (zuvor: generischer status_update-Text).
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


@dataclass(frozen=True, slots=True)
class MailTemplateSpec:
    """Builtin-Spezifikation einer Mail (Versand-Fallback + Editor-Default)."""

    key: str
    kind: str
    subject_i18n: dict[str, str]
    body_i18n: dict[str, str]
    placeholders: dict[str, str]


# Reihenfolge = Anzeigereihenfolge im Editor.
TEMPLATE_CATALOGUE: tuple[MailTemplateSpec, ...] = (
    MailTemplateSpec(
        "status_update",
        "status_update",
        _svc._BUILTIN_NOTIFY_SUBJECT,  # noqa: SLF001 — gemeinsamer Builtin
        _svc._BUILTIN_NOTIFY_BODY,  # noqa: SLF001
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
)

CATALOGUE_BY_KEY: dict[str, MailTemplateSpec] = {s.key: s for s in TEMPLATE_CATALOGUE}

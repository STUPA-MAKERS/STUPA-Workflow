"""Central catalogue of all notification mail templates.

This module lists every mail the platform sends under its ``key``. An entry holds the
builtin subject and body plus the placeholder hints. The subject and the body are the
same objects that the sender uses as fallback.

The editor (`/admin/mail-templates`) shows every mail through this catalogue. A DB
override wins when it exists, otherwise the builtin default applies. The editor and the
real send therefore never drift apart. Nothing copies a seed into the DB.

The module imports the builtins from the sender modules. Only ``task_reminder`` (the
worker sends it) and ``status_update_team`` live here as the single source.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.notifications import (
    action_dispatcher,
    auto,
    captured,
    comments,
    mentions,
    polls,
    privacy,
    tickets,
    todos,
)
from app.modules.notifications import service as _svc

#: Subject of ``task_reminder``. The worker (``worker/task_reminders.py``) sends it and
#: imports these constants from here, because the app never imports the worker.
TASK_REMINDER_SUBJECT: dict[str, str] = {
    "de": "Erinnerung: offene Aufgabe"
    "{% if applicationTitle %} — „{{ applicationTitle }}“{% endif %}",
    "en": 'Reminder: open task{% if applicationTitle %} — "{{ applicationTitle }}"{% endif %}',
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
#: Subject of ``status_update_team``, the team default of a ``notify`` action without
#: ``templateKey``, because ``status_update`` reads "Your application".
STATUS_UPDATE_TEAM_SUBJECT: dict[str, str] = {
    "de": "Statuswechsel: Antrag{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": 'Status change: application{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
}
STATUS_UPDATE_TEAM_BODY: dict[str, str] = {
    "de": "Hallo,\n\nder Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} ist in einen "
    "neuen Status gewechselt{% if status %}: {{ status }}{% endif %}."
    + _svc.DECISION_BLOCK["de"]
    + "\n\nGgf. ist eine Aktion oder Abstimmung erforderlich.\n",
    "en": "Hello,\n\nthe application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} moved to a '
    "new state{% if status %}: {{ status }}{% endif %}."
    + _svc.DECISION_BLOCK["en"]
    + "\n\nAn action or vote may be required.\n",
}


@dataclass(frozen=True, slots=True)
class MailTemplateSpec:
    """Builtin spec of a mail: the send fallback and the editor default."""

    key: str
    kind: str
    subject_i18n: dict[str, str]
    body_i18n: dict[str, str]
    placeholders: dict[str, str]


#: Mail kinds in the display order of the editor. ``status_update`` shares the builtin of
#: the notification service.
TEMPLATE_CATALOGUE: tuple[MailTemplateSpec, ...] = (
    MailTemplateSpec(
        "status_update",
        "status_update",
        _svc._BUILTIN_NOTIFY_SUBJECT,
        _svc._BUILTIN_NOTIFY_BODY,
        {
            "link": "Link zum Antrag (ohne den Platzhalter hängt die Mail ihn an)",
            "applicationTitle": "Titel des Antrags",
            "status": "Neuer Status",
            "applicationId": "ID des Antrags",
            "requestedAmount": "Beantragter Betrag",
            "approvedAmount": "Bewilligter Betrag",
            "amountDeviates": "Bewilligter Betrag weicht ab (ja/nein)",
            "conditions": "Liste der Auflagen",
        },
    ),
    MailTemplateSpec(
        "status_update_team",
        "status_update",
        STATUS_UPDATE_TEAM_SUBJECT,
        STATUS_UPDATE_TEAM_BODY,
        {
            "link": "Link zum Antrag (ohne den Platzhalter hängt die Mail ihn an)",
            "applicationTitle": "Titel des Antrags",
            "status": "Neuer Status",
            "applicationId": "ID des Antrags",
            "requestedAmount": "Beantragter Betrag",
            "approvedAmount": "Bewilligter Betrag",
            "amountDeviates": "Bewilligter Betrag weicht ab (ja/nein)",
            "conditions": "Liste der Auflagen",
        },
    ),
    MailTemplateSpec(
        "task_new",
        "task",
        action_dispatcher._BUILTIN_TASK_SUBJECT,
        action_dispatcher._BUILTIN_TASK_BODY,
        {
            "link": "Link zur Aufgabe (ohne den Platzhalter hängt die Mail ihn an)",
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
            "link": "Link zur Aufgabe (ohne den Platzhalter hängt die Mail ihn an)",
            "applicationTitle": "Titel des Antrags",
            "status": "Aktueller Status",
            "daysOpen": "Tage ohne Aktion",
            "applicationId": "ID des Antrags",
        },
    ),
    MailTemplateSpec(
        "comment_applicant",
        "comment",
        comments._BUILTIN_APPLICANT_SUBJECT,
        comments._BUILTIN_APPLICANT_BODY,
        {
            "link": "Link zum Antrag (ohne den Platzhalter hängt die Mail ihn an)",
            "applicationTitle": "Titel des Antrags",
            "status": "Aktueller Status",
            "comment": "Kommentartext (Auszug)",
            "commentAuthor": "Name des Gremiums (nie der Name des Mitglieds)",
            "commentAuthorInitials": "Initialen des Gremiums",
            "applicationId": "ID des Antrags",
        },
    ),
    MailTemplateSpec(
        "comment_team",
        "comment",
        comments._BUILTIN_TEAM_SUBJECT,
        comments._BUILTIN_TEAM_BODY,
        {
            "link": "Link zum Antrag (ohne den Platzhalter hängt die Mail ihn an)",
            "applicationTitle": "Titel des Antrags",
            "status": "Aktueller Status",
            "comment": "Kommentartext (Auszug)",
            "commentAuthor": "Name der Kommentar-Autor:in",
            "commentAuthorInitials": "Initialen der Kommentar-Autor:in",
            "applicationId": "ID des Antrags",
        },
    ),
    MailTemplateSpec(
        mentions.COMMENT_MENTIONED_KEY,
        mentions.MENTION_KIND,
        mentions.COMMENT_MENTIONED_SUBJECT,
        mentions.COMMENT_MENTIONED_BODY,
        mentions.COMMENT_MENTIONED_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        "meeting_created",
        "meeting",
        auto._BUILTIN_MEETING_SUBJECT,
        auto._BUILTIN_MEETING_BODY,
        {
            "link": "Link zur Sitzung (ohne den Platzhalter hängt die Mail ihn an)",
            "meetingTitle": "Titel der Sitzung",
            "meetingDate": "Datum",
            "meetingTime": "Uhrzeit",
            "gremiumName": "Gremium",
            "meetingId": "ID der Sitzung",
        },
    ),
    MailTemplateSpec(
        "delegation_granted",
        "delegation",
        auto._BUILTIN_DELEGATION_GRANTED_SUBJECT,
        auto._BUILTIN_DELEGATION_GRANTED_BODY,
        {
            "link": "Link zur Sitzung (ohne den Platzhalter hängt die Mail ihn an)",
            "meetingTitle": "Titel der Sitzung",
            "delegatorName": "Vollmachtgeber:in",
        },
    ),
    MailTemplateSpec(
        "delegation_revoked",
        "delegation",
        auto._BUILTIN_DELEGATION_REVOKED_SUBJECT,
        auto._BUILTIN_DELEGATION_REVOKED_BODY,
        {
            "link": "Link zur Sitzung (ohne den Platzhalter hängt die Mail ihn an)",
            "meetingTitle": "Titel der Sitzung",
            "delegatorName": "Vollmachtgeber:in",
        },
    ),
    MailTemplateSpec(
        "magic_link",
        "magic_link",
        _svc._BUILTIN_MAGIC_LINK_SUBJECT,
        _svc._BUILTIN_MAGIC_LINK_BODY,
        {"link": "Anmelde-Link"},
    ),
    MailTemplateSpec(
        captured.APPLICATION_CAPTURED_KEY,
        captured.APPLICATION_CAPTURED_KEY,
        captured.APPLICATION_CAPTURED_SUBJECT,
        captured.APPLICATION_CAPTURED_BODY,
        captured.APPLICATION_CAPTURED_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        "erasure_requested",
        "privacy",
        privacy.ERASURE_REQUESTED_SUBJECT,
        privacy.ERASURE_REQUESTED_BODY,
        {
            "link": "Link zur Datenschutz-Verwaltung (ohne den Platzhalter hängt die Mail ihn an)",
            "subjectType": "Art (applicant/principal)",
            "requestId": "ID des Löschantrags",
        },
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
        {
            "link": "Link zum Antrag (ohne den Platzhalter hängt die Mail ihn an)",
            "reason": "Ablehnungsgrund",
            "requestId": "ID des Löschantrags",
        },
    ),
    MailTemplateSpec(
        tickets.TICKET_CREATED_KEY,
        tickets.TICKET_CREATED_KEY,
        tickets.TICKET_CREATED_SUBJECT,
        tickets.TICKET_CREATED_BODY,
        tickets.TICKET_CREATED_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        tickets.TICKET_RECEIVED_KEY,
        tickets.TICKET_RECEIVED_KEY,
        tickets.TICKET_RECEIVED_SUBJECT,
        tickets.TICKET_RECEIVED_BODY,
        tickets.TICKET_RECEIVED_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        tickets.TICKET_ANSWER_KEY,
        tickets.TICKET_ANSWER_KEY,
        tickets.TICKET_ANSWER_SUBJECT,
        tickets.TICKET_ANSWER_BODY,
        tickets.TICKET_ANSWER_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        tickets.TICKET_MESSAGE_KEY,
        tickets.TICKET_MESSAGE_KEY,
        tickets.TICKET_MESSAGE_SUBJECT,
        tickets.TICKET_MESSAGE_BODY,
        tickets.TICKET_MESSAGE_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        polls.POLL_STARTED_KEY,
        polls.POLL_STARTED_KEY,
        polls.POLL_STARTED_SUBJECT,
        polls.POLL_STARTED_BODY,
        polls.POLL_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        polls.POLL_REMINDER_KEY,
        polls.POLL_REMINDER_KEY,
        polls.POLL_REMINDER_SUBJECT,
        polls.POLL_REMINDER_BODY,
        polls.POLL_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        todos.TODO_ASSIGNED_KEY,
        todos.TODO_ASSIGNED_KEY,
        todos.TODO_ASSIGNED_SUBJECT,
        todos.TODO_ASSIGNED_BODY,
        todos.TODO_ASSIGNED_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        todos.TODO_MENTIONED_KEY,
        todos.TODO_MENTIONED_KEY,
        todos.TODO_MENTIONED_SUBJECT,
        todos.TODO_MENTIONED_BODY,
        todos.TODO_MENTIONED_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        todos.TODO_DUE_KEY,
        todos.TODO_DUE_KEY,
        todos.TODO_DUE_SUBJECT,
        todos.TODO_DUE_BODY,
        todos.TODO_DUE_PLACEHOLDERS,
    ),
    MailTemplateSpec(
        mentions.TICKET_MENTIONED_KEY,
        mentions.MENTION_KIND,
        mentions.TICKET_MENTIONED_SUBJECT,
        mentions.TICKET_MENTIONED_BODY,
        mentions.TICKET_MENTIONED_PLACEHOLDERS,
    ),
)

CATALOGUE_BY_KEY: dict[str, MailTemplateSpec] = {s.key: s for s in TEMPLATE_CATALOGUE}

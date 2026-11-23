"""The push side of the notification kinds: the defaults and the push titles.

Push uses the kinds of `kinds.NOTIFICATION_KINDS`, each with its own switch
(§F/collaboration/notifications/002501). After a person switches push on, only the
urgent kinds are on (002502): too many pushes make people switch push off entirely.

The title of a push names its kind (002503); the one short line under it is the subject
of the mail of the same event.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.modules.notifications.kinds import NOTIFICATION_KINDS

#: The kinds that push after a person switches push on: mentions, an assigned to-do, a
#: started poll and a meeting.
PUSH_DEFAULT_ON_KINDS: frozenset[str] = frozenset(
    {"mention", "todo_mentioned", "todo_assigned", "poll_started", "meeting"}
)


def push_default(kind: str) -> bool:
    """Return the push switch of ``kind`` for a person who never changed it."""
    return kind in PUSH_DEFAULT_ON_KINDS


#: The title of a push per kind and language. A kind without an entry takes the
#: platform name, so a new kind never pushes without a title.
PUSH_TITLES: Mapping[str, Mapping[str, str]] = {
    "status_update": {"de": "Neuer Status", "en": "New status"},
    "status_update_team": {"de": "Neuer Status", "en": "New status"},
    "comment": {"de": "Neuer Kommentar", "en": "New comment"},
    "task": {"de": "Neue Aufgabe", "en": "New task"},
    "task_reminder": {"de": "Offene Aufgabe", "en": "Open task"},
    "meeting": {"de": "Sitzung", "en": "Meeting"},
    "delegation": {"de": "Vertretung", "en": "Delegation"},
    "protocol": {"de": "Protokoll", "en": "Minutes"},
    "privacy": {"de": "Datenschutz", "en": "Privacy"},
    "ticket_created": {"de": "Neues Ticket", "en": "New ticket"},
    "ticket_message": {"de": "Neue Nachricht", "en": "New message"},
    "ticket_answer": {"de": "Neue Antwort", "en": "New answer"},
    "todo_assigned": {"de": "To-Do zugewiesen", "en": "To-do assigned"},
    "todo_mentioned": {"de": "Neue Erwähnung", "en": "New mention"},
    "todo_due": {"de": "To-Do fällig", "en": "To-do due"},
    "todo_board_added": {"de": "Neues Board", "en": "New board"},
    "mention": {"de": "Neue Erwähnung", "en": "New mention"},
    "poll_started": {"de": "Abstimmung gestartet", "en": "Poll started"},
    "poll_reminder": {"de": "Abstimmung endet bald", "en": "Poll ends soon"},
    "appointment": {"de": "Termin", "en": "Appointment"},
    "draft_reminder": {"de": "Entwurf offen", "en": "Draft open"},
}

#: The labels of the push buttons per language.
BUTTON_LABELS: Mapping[str, Mapping[str, str]] = {
    "open": {"de": "Öffnen", "en": "Open"},
    "open_poll": {"de": "Zur Abstimmung", "en": "To the poll"},
    "appointment_accept": {"de": "Zusagen", "en": "Accept"},
    "appointment_decline": {"de": "Absagen", "en": "Decline"},
    "todo_done": {"de": "Erledigt", "en": "Done"},
}


def push_title(kind: str, lang: str, fallback: str) -> str:
    """Return the title of a push of ``kind`` in ``lang``, else German, else ``fallback``."""
    texts = PUSH_TITLES.get(kind, {})
    return texts.get(lang) or texts.get("de") or fallback


def button_label(key: str, lang: str) -> str:
    """Return the label of the push button ``key`` in ``lang``, else German."""
    texts = BUTTON_LABELS[key]
    return texts.get(lang) or texts["de"]


def is_push_kind(kind: str) -> bool:
    """Return whether ``kind`` has a push switch (every kind of the mail catalogue)."""
    return kind in NOTIFICATION_KINDS

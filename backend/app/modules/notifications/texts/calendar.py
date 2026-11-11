"""Builtin texts of the Termin mails.

The mail catalogue reads them for the template editor. The sender is in
`calendar.mails` and uses the same objects as its fallback. The three templates are
one notification kind (`APPOINTMENT_KIND`), so one switch covers them.
"""

from __future__ import annotations

APPOINTMENT_KIND = "appointment"
APPOINTMENT_INVITED_KEY = "appointment_invited"
APPOINTMENT_CHANGED_KEY = "appointment_changed"
APPOINTMENT_CANCELLED_KEY = "appointment_cancelled"

APPOINTMENT_INVITED_SUBJECT: dict[str, str] = {
    "de": "Einladung: {{ title }}",
    "en": "Invitation: {{ title }}",
}
APPOINTMENT_INVITED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ actor }} lädt Sie zum Termin „{{ title }}“ ein.\n\n"
    "Zeit: {{ when }}\n{% if place %}Ort: {{ place }}\n{% endif %}",
    "en": 'Hello,\n\n{{ actor }} invites you to the appointment "{{ title }}".\n\n'
    "Time: {{ when }}\n{% if place %}Place: {{ place }}\n{% endif %}",
}

APPOINTMENT_CHANGED_SUBJECT: dict[str, str] = {
    "de": "Geändert: {{ title }}",
    "en": "Changed: {{ title }}",
}
APPOINTMENT_CHANGED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ actor }} hat den Termin „{{ title }}“ geändert.\n\n"
    "Zeit: {{ when }}\n{% if place %}Ort: {{ place }}\n{% endif %}",
    "en": 'Hello,\n\n{{ actor }} changed the appointment "{{ title }}".\n\n'
    "Time: {{ when }}\n{% if place %}Place: {{ place }}\n{% endif %}",
}

APPOINTMENT_CANCELLED_SUBJECT: dict[str, str] = {
    "de": "Abgesagt: {{ title }}",
    "en": "Cancelled: {{ title }}",
}
APPOINTMENT_CANCELLED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ actor }} hat den Termin „{{ title }}“ am {{ when }} gelöscht.\n",
    "en": 'Hello,\n\n{{ actor }} deleted the appointment "{{ title }}" on {{ when }}.\n',
}

APPOINTMENT_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Termin (ohne den Platzhalter hängt die Mail ihn an)",
    "title": "Titel des Termins",
    "when": "Beginn und Ende des Termins",
    "place": "Ort des Termins (kann leer sein)",
    "actor": "Name der Person, die eingeladen, geändert oder gelöscht hat",
}

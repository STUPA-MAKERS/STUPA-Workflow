"""Builtin texts of the ticket mails.

The mail catalogue reads them for the template editor. The sender is in
`tickets.mails` and uses the same objects as its fallback.
"""

from __future__ import annotations

TICKET_CREATED_KEY = "ticket_created"
TICKET_RECEIVED_KEY = "ticket_received"
TICKET_ANSWER_KEY = "ticket_answer"
TICKET_MESSAGE_KEY = "ticket_message"
TICKET_ASSIGNED_KEY = "ticket_assigned"

KIND_DE = (
    "{% if kind == 'bug' %}Problem{% elif kind == 'question' %}Frage"
    "{% elif kind == 'barrier' %}Barriere{% elif kind == 'idea' %}Idee"
    "{% else %}{{ area }}{% endif %}"
)
KIND_EN = (
    "{% if kind == 'bug' %}problem{% elif kind == 'question' %}question"
    "{% elif kind == 'barrier' %}barrier{% elif kind == 'idea' %}idea"
    "{% else %}{{ area }}{% endif %}"
)

TICKET_CREATED_SUBJECT: dict[str, str] = {
    "de": "Neues Ticket {{ number }}: {{ title }}",
    "en": "New ticket {{ number }}: {{ title }}",
}
TICKET_CREATED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ reporter }} hat ein neues Ticket gemeldet (" + KIND_DE + "):\n\n"
    "{{ number }} · {{ title }}\n",
    "en": "Hello,\n\n{{ reporter }} reported a new ticket (" + KIND_EN + "):\n\n"
    "{{ number }} · {{ title }}\n",
}
TICKET_CREATED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Ticket (ohne den Platzhalter hängt die Mail ihn an)",
    "number": "Ticketnummer (T-7K3QX9MD)",
    "title": "Titel des Tickets",
    "kind": "Art (bug/question/idea/barrier, leer außerhalb des Bereichs Plattform)",
    "area": "Name des Bereichs",
    "reporter": "Name oder E-Mail der meldenden Person",
}

TICKET_RECEIVED_SUBJECT: dict[str, str] = {
    "de": "Ihre Meldung {{ number }} ist eingegangen",
    "en": "Your report {{ number }} was received",
}
TICKET_RECEIVED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nvielen Dank für Ihre Meldung{% if title %} „{{ title }}“{% endif %}. "
    "Sie hat die Nummer "
    "{{ number }}. {% if link %}Antworten und den Stand finden Sie unter „Tickets“."
    "{% else %}Bei Rückfragen melden wir uns per E-Mail.{% endif %}\n\n"
    "Antworten auf viele Fragen stehen im Handbuch: {{ wikiUrl }}\n",
    "en": "Hello,\n\nthank you for your report"
    '{% if title %} "{{ title }}"{% endif %}. Its number is '
    "{{ number }}. {% if link %}You find the answers and the status under "
    '"Tickets".{% else %}If we have questions, we will contact you by email.{% endif %}'
    "\n\n"
    "The handbook answers many questions: {{ wikiUrl }}\n",
}
TICKET_RECEIVED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Ticket (leer bei einer Meldung ohne Anmeldung)",
    "number": "Ticketnummer (T-7K3QX9MD)",
    "title": "Titel des Tickets (leer bei einer Meldung ohne Anmeldung)",
    "wikiUrl": "Link zum Handbuch",
}


TICKET_ANSWER_SUBJECT: dict[str, str] = {
    "de": "Antwort auf Ihr Ticket {{ number }}",
    "en": "Reply to your ticket {{ number }}",
}
TICKET_ANSWER_BODY: dict[str, str] = {
    "de": "Hallo,\n\nzu Ihrem Ticket {{ number }} „{{ title }}“ gibt es eine neue "
    "Nachricht{% if author %} von {{ author }}{% endif %}:\n\n{{ message }}\n",
    "en": 'Hello,\n\nthere is a new message on your ticket {{ number }} "{{ title }}"'
    "{% if author %} from {{ author }}{% endif %}:\n\n{{ message }}\n",
}
TICKET_ANSWER_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Ticket (ohne den Platzhalter hängt die Mail ihn an)",
    "number": "Ticketnummer (T-7K3QX9MD)",
    "title": "Titel des Tickets",
    "author": "Name des Teammitglieds (leer ohne Namen)",
    "message": "Text der Nachricht (ohne Text die Namen der Dateien)",
}

TICKET_MESSAGE_SUBJECT: dict[str, str] = {
    "de": "Neue Nachricht zu Ticket {{ number }}: {{ title }}",
    "en": "New message on ticket {{ number }}: {{ title }}",
}
TICKET_MESSAGE_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ reporter }} hat zum Ticket {{ number }} „{{ title }}“ "
    "geschrieben:\n\n{{ message }}\n",
    "en": 'Hello,\n\n{{ reporter }} wrote on the ticket {{ number }} "{{ title }}":'
    "\n\n{{ message }}\n",
}
TICKET_MESSAGE_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Ticket (ohne den Platzhalter hängt die Mail ihn an)",
    "number": "Ticketnummer (T-7K3QX9MD)",
    "title": "Titel des Tickets",
    "reporter": "Name oder E-Mail der meldenden Person",
    "message": "Text der Nachricht (ohne Text die Namen der Dateien)",
}

TICKET_ASSIGNED_SUBJECT: dict[str, str] = {
    "de": "Ticket {{ number }} wurde Ihnen zugewiesen: {{ title }}",
    "en": "Ticket {{ number }} was assigned to you: {{ title }}",
}
TICKET_ASSIGNED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{% if actor %}{{ actor }} hat Ihnen{% else %}Ihnen wurde{% endif %} "
    "das Ticket {{ number }} „{{ title }}“ zugewiesen.\n",
    "en": "Hello,\n\n{% if actor %}{{ actor }} assigned{% else %}Somebody assigned{% endif %} "
    'the ticket {{ number }} "{{ title }}" to you.\n',
}
TICKET_ASSIGNED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Ticket (ohne den Platzhalter hängt die Mail ihn an)",
    "number": "Ticketnummer (T-7K3QX9MD)",
    "title": "Titel des Tickets",
    "actor": "Name der Person, die zugewiesen hat (leer ohne Namen)",
}

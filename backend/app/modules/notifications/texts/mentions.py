"""Builtin texts of the mention mails.

The mail catalogue reads them for the template editor. The senders are in
`applications.mention_mails` and `tickets.mention_mails` and use the same objects
as their fallback.
"""

from __future__ import annotations

from app.modules.notifications.texts.comments import (
    CHAT_BUBBLE_HTML,
)

#: The opt-out kind of both mention mails.
MENTION_KIND = "mention"
COMMENT_MENTIONED_KEY = "comment_mentioned"
TICKET_MENTIONED_KEY = "ticket_mentioned"

COMMENT_MENTIONED_SUBJECT: dict[str, str] = {
    "de": "{{ actor }} hat Sie erwähnt: {{ applicationTitle }}",
    "en": "{{ actor }} mentioned you: {{ applicationTitle }}",
}
COMMENT_MENTIONED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ actor }} hat Sie in einem Kommentar zum Antrag "
    "„{{ applicationTitle }}“ erwähnt:\n\n{{ comment }}\n",
    "en": "Hello,\n\n{{ actor }} mentioned you in a comment on the application "
    '"{{ applicationTitle }}":\n\n{{ comment }}\n',
}
COMMENT_MENTIONED_HTML: dict[str, str] = {
    "de": '<p style="margin:0 0 1em;">Hallo,</p>'
    '<p style="margin:0;">{{ actor }} hat Sie in einem Kommentar zum Antrag '
    "„{{ applicationTitle }}“ erwähnt:</p>" + CHAT_BUBBLE_HTML,
    "en": '<p style="margin:0 0 1em;">Hello,</p>'
    '<p style="margin:0;">{{ actor }} mentioned you in a comment on the application '
    '"{{ applicationTitle }}":</p>' + CHAT_BUBBLE_HTML,
}
COMMENT_MENTIONED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Kommentar (ohne den Platzhalter hängt die Mail ihn an)",
    "actor": "Name der Person, die erwähnt hat",
    "applicationTitle": "Titel des Antrags",
    "applicationId": "ID des Antrags",
    "comment": "Kommentartext (Auszug; ohne Text die Namen der Dateien)",
    "commentAuthor": "Name der Kommentar-Autor:in",
    "commentAuthorInitials": "Initialen der Kommentar-Autor:in",
}

#: Chat bubble of the comment mails, with the placeholder names of the ticket context.
NOTE_BUBBLE_HTML = (
    CHAT_BUBBLE_HTML.replace("{{ commentAuthorInitials }}", "{{ authorInitials }}")
    .replace("{{ commentAuthor }}", "{{ author }}")
    .replace("{{ comment |", "{{ message |")
)

TICKET_MENTIONED_SUBJECT: dict[str, str] = {
    "de": "{{ actor }} hat Sie erwähnt: {{ number }} · {{ title }}",
    "en": "{{ actor }} mentioned you: {{ number }} · {{ title }}",
}
TICKET_MENTIONED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ actor }} hat Sie in einer Notiz zum Ticket {{ number }} "
    "„{{ title }}“ erwähnt:\n\n{{ message }}\n",
    "en": "Hello,\n\n{{ actor }} mentioned you in a note on the ticket {{ number }} "
    '"{{ title }}":\n\n{{ message }}\n',
}
TICKET_MENTIONED_HTML: dict[str, str] = {
    "de": '<p style="margin:0 0 1em;">Hallo,</p>'
    '<p style="margin:0;">{{ actor }} hat Sie in einer Notiz zum Ticket {{ number }} '
    "„{{ title }}“ erwähnt:</p>" + NOTE_BUBBLE_HTML,
    "en": '<p style="margin:0 0 1em;">Hello,</p>'
    '<p style="margin:0;">{{ actor }} mentioned you in a note on the ticket {{ number }} '
    '"{{ title }}":</p>' + NOTE_BUBBLE_HTML,
}
TICKET_MENTIONED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zur Notiz (ohne den Platzhalter hängt die Mail ihn an)",
    "actor": "Name der Person, die erwähnt hat",
    "number": "Ticketnummer (T-0042)",
    "title": "Titel des Tickets",
    "message": "Text der Notiz (Auszug; ohne Text die Namen der Dateien)",
    "author": "Name der Autor:in der Notiz",
    "authorInitials": "Initialen der Autor:in der Notiz",
}

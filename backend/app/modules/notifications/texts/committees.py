"""Builtin texts of the message of a Gremium to its members (``gremium_message``).

The mail catalogue reads them for the template editor. The sender is in
`gremien_overview.notify` and uses the same objects as its fallback. The mail is in no
notification kind, so a member cannot switch it off (spec 001853).
"""

from __future__ import annotations

GREMIUM_MESSAGE_KEY = "gremium_message"

GREMIUM_MESSAGE_SUBJECT: dict[str, str] = {
    "de": "{{ gremiumName }}: {{ subject }}",
    "en": "{{ gremiumName }}: {{ subject }}",
}
GREMIUM_MESSAGE_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ senderName }} schreibt an die Mitglieder des Gremiums "
    "{{ gremiumName }}:\n\n{{ message }}\n",
    "en": "Hello,\n\n{{ senderName }} writes to the members of the committee "
    "{{ gremiumName }}:\n\n{{ message }}\n",
}
GREMIUM_MESSAGE_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Gremium (ohne den Platzhalter hängt die Mail ihn an)",
    "gremiumName": "Name des Gremiums",
    "senderName": "Name der Person, die die Nachricht schickt",
    "subject": "Betreff der Nachricht",
    "message": "Text der Nachricht",
}

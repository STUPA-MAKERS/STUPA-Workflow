"""Builtin texts of the poll mails.

The mail catalogue reads them for the template editor. The sender is in
`voting.poll_mails` and uses the same objects as its fallback.
"""

from __future__ import annotations

POLL_STARTED_KEY = "poll_started"
POLL_REMINDER_KEY = "poll_reminder"

POLL_STARTED_SUBJECT: dict[str, str] = {
    "de": "Neue Umfrage: {{ question }}",
    "en": "New poll: {{ question }}",
}
POLL_STARTED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nim Gremium {{ gremiumName }} läuft eine Umfrage:\n\n{{ question }}\n\n"
    "Sie endet am {{ closesAt }}.\n",
    "en": "Hello,\n\nthe committee {{ gremiumName }} runs a poll:\n\n{{ question }}\n\n"
    "It ends on {{ closesAt }}.\n",
}
POLL_REMINDER_SUBJECT: dict[str, str] = {
    "de": "Erinnerung: Umfrage „{{ question }}“",
    "en": 'Reminder: poll "{{ question }}"',
}
POLL_REMINDER_BODY: dict[str, str] = {
    "de": "Hallo,\n\ndie Umfrage „{{ question }}“ im Gremium {{ gremiumName }} endet am "
    "{{ closesAt }}. Sie haben noch nicht geantwortet.\n",
    "en": 'Hello,\n\nthe poll "{{ question }}" of the committee {{ gremiumName }} ends on '
    "{{ closesAt }}. You have not answered yet.\n",
}
POLL_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zur Umfrage (ohne den Platzhalter hängt die Mail ihn an)",
    "question": "Frage der Umfrage",
    "gremiumName": "Name des Gremiums",
    "closesAt": "Ende der Umfrage (TT.MM.JJJJ, HH:MM)",
}

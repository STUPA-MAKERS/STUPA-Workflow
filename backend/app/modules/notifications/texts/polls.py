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

#: The mails of an Umlaufverfahren (§F/meetings/voting/000944). They are in no
#: notification kind: a ballot that is not cast counts as a no, so a member cannot
#: switch them off.
CIRCULAR_OPEN_KEY = "circular_open"
CIRCULAR_REMINDER_KEY = "circular_reminder"

CIRCULAR_OPEN_SUBJECT: dict[str, str] = {
    "de": "Umlaufverfahren: {{ question }}",
    "en": "Circular vote: {{ question }}",
}
CIRCULAR_OPEN_BODY: dict[str, str] = {
    "de": "Hallo,\n\nim Gremium {{ gremiumName }} läuft ein Umlaufverfahren:\n\n"
    "{{ question }}\n\nDie Stimmabgabe endet am {{ closesAt }}. Eine nicht abgegebene "
    "Stimme zählt wie ein Nein.\n",
    "en": "Hello,\n\nthe committee {{ gremiumName }} runs a circular vote:\n\n"
    "{{ question }}\n\nThe cast window ends on {{ closesAt }}. A ballot that is not "
    "cast counts as a no.\n",
}
CIRCULAR_REMINDER_SUBJECT: dict[str, str] = {
    "de": "Erinnerung: Umlaufverfahren „{{ question }}“",
    "en": 'Reminder: circular vote "{{ question }}"',
}
CIRCULAR_REMINDER_BODY: dict[str, str] = {
    "de": "Hallo,\n\ndas Umlaufverfahren „{{ question }}“ im Gremium {{ gremiumName }} "
    "endet am {{ closesAt }}. Sie haben noch nicht abgestimmt. Eine nicht abgegebene "
    "Stimme zählt wie ein Nein.\n",
    "en": 'Hello,\n\nthe circular vote "{{ question }}" of the committee '
    "{{ gremiumName }} ends on {{ closesAt }}. You have not cast a ballot yet. A ballot "
    "that is not cast counts as a no.\n",
}
CIRCULAR_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Umlaufverfahren (ohne den Platzhalter hängt die Mail ihn an)",
    "question": "Frage des Umlaufverfahrens",
    "gremiumName": "Name des Gremiums",
    "closesAt": "Ende der Stimmabgabe (TT.MM.JJJJ, HH:MM)",
}

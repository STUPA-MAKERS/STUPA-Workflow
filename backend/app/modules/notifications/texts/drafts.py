"""Builtin texts of the draft reminder (spec 001711).

The mail catalogue reads them for the template editor. The sender is the worker
(`worker/drafts.py`), which uses the same objects as its fallback.
"""

from __future__ import annotations

#: The template key, the notification kind and the footer kind of the mail.
DRAFT_REMINDER_KEY = "draft_reminder"

DRAFT_REMINDER_SUBJECT: dict[str, str] = {
    "de": "Dein Antrag ist noch nicht eingereicht"
    "{% if applicationTitle %}: „{{ applicationTitle }}“{% endif %}",
    "en": "Your application is not submitted yet"
    '{% if applicationTitle %}: "{{ applicationTitle }}"{% endif %}',
}
DRAFT_REMINDER_BODY: dict[str, str] = {
    "de": "Hallo,\n\ndein Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} "
    "ist seit {{ daysIdle }} Tagen ein Entwurf. Das Gremium sieht ihn erst, wenn du ihn "
    "einreichst. Öffne den Antrag und wähle „Einreichen“:\n{{ link }}\n",
    "en": "Hello,\n\nyour application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} '
    "has been a draft for {{ daysIdle }} days. The committee sees it only after you "
    'submit it. Open the application and choose "Submit":\n{{ link }}\n',
}
DRAFT_REMINDER_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Entwurf",
    "applicationTitle": "Titel des Antrags",
    "applicationId": "ID des Antrags",
    "daysIdle": "Tage ohne Änderung",
}

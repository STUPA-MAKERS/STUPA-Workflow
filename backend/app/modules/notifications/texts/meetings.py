"""Builtin texts of the meeting and delegation mails.

The mail catalogue reads them for the template editor. The senders are in
`delegations.mails` and `livevote.mails` and use the same
objects as their fallback.
"""

from __future__ import annotations

BUILTIN_MEETING_SUBJECT = {
    "de": "Neue Sitzung: {{ meetingTitle }}{% if gremiumName %} ({{ gremiumName }}){% endif %}",
    "en": "New meeting: {{ meetingTitle }}{% if gremiumName %} ({{ gremiumName }}){% endif %}",
}
BUILTIN_MEETING_BODY = {
    "de": "Hallo,\n\nfür dein Gremium{% if gremiumName %} {{ gremiumName }}"
    "{% endif %} wurde eine Sitzung angesetzt:\n\n{{ meetingTitle }}"
    "{% if meetingDate %}\nDatum: {{ meetingDate }}{% endif %}"
    "{% if meetingTime %}, {{ meetingTime }} Uhr{% endif %}\n",
    "en": "Hello,\n\na meeting was scheduled for your committee"
    "{% if gremiumName %} {{ gremiumName }}{% endif %}:\n\n{{ meetingTitle }}"
    "{% if meetingDate %}\nDate: {{ meetingDate }}{% endif %}"
    "{% if meetingTime %}, {{ meetingTime }}{% endif %}\n",
}

#: The mail to the persons with ``session.manage`` when the unexcused absences of a
#: member reach the limit of a term, or the limit minus 1.
BUILTIN_ABSENCE_LIMIT_SUBJECT = {
    "de": "Unentschuldigtes Fehlen: {{ memberName }}{% if gremiumName %} ({{ gremiumName }})"
    "{% endif %}",
    "en": "Unexcused absence: {{ memberName }}{% if gremiumName %} ({{ gremiumName }}){% endif %}",
}
BUILTIN_ABSENCE_LIMIT_BODY = {
    "de": "Hallo,\n\n{{ memberName }} hat in der Sitzung „{{ meetingTitle }}“"
    "{% if meetingDate %} am {{ meetingDate }}{% endif %} unentschuldigt gefehlt. "
    "Das ist das {{ count }}. unentschuldigte Fehlen in dieser Amtszeit"
    "{% if gremiumName %} im Gremium {{ gremiumName }}{% endif %}.\n\n"
    "{% if reached %}Die Grenze von {{ limit }} ist erreicht. Der Verlust des Mandats "
    "gehört auf die Tagesordnung der nächsten Sitzung.{% else %}Die Grenze liegt bei "
    "{{ limit }}. Das Mitglied ist zu verwarnen.{% endif %}\n",
    "en": "Hello,\n\n{{ memberName }} was absent without an excuse in the meeting "
    '"{{ meetingTitle }}"{% if meetingDate %} on {{ meetingDate }}{% endif %}. '
    "This is unexcused absence number {{ count }} in this term"
    "{% if gremiumName %} in the committee {{ gremiumName }}{% endif %}.\n\n"
    "{% if reached %}The limit of {{ limit }} is reached. The loss of the mandate "
    "belongs on the agenda of the next meeting.{% else %}The limit is {{ limit }}. "
    "The member is to be warned.{% endif %}\n",
}

#: The mail to the persons with ``session.manage`` when a member hands in a late
#: excuse for a closed meeting (§F/meetings/meetings/000943).
BUILTIN_LATE_EXCUSE_SUBJECT = {
    "de": "Nachträgliche Entschuldigung: {{ memberName }}{% if gremiumName %} "
    "({{ gremiumName }}){% endif %}",
    "en": "Late excuse: {{ memberName }}{% if gremiumName %} ({{ gremiumName }}){% endif %}",
}
BUILTIN_LATE_EXCUSE_BODY = {
    "de": "Hallo,\n\n{{ memberName }} hat sich für die Sitzung „{{ meetingTitle }}“"
    "{% if meetingDate %} am {{ meetingDate }}{% endif %} nachträglich entschuldigt. "
    "Die Entschuldigung gilt sofort, das Fehlen zählt nicht mehr als unentschuldigt.\n\n"
    "Grund: {{ reason }}\n",
    "en": "Hello,\n\n{{ memberName }} handed in a late excuse for the meeting "
    '"{{ meetingTitle }}"{% if meetingDate %} on {{ meetingDate }}{% endif %}. '
    "The excuse applies at once, the absence no longer counts as unexcused.\n\n"
    "Reason: {{ reason }}\n",
}

#: Builtin subject of a meeting-bound delegation mail to the substitute. The context
#: names the meeting, the Gremium and the delegating member.
BUILTIN_DELEGATION_GRANTED_SUBJECT = {
    "de": "Vertretung erhalten: {{ meetingTitle }}",
    "en": "Proxy received: {{ meetingTitle }}",
}
BUILTIN_DELEGATION_GRANTED_BODY = {
    "de": "Hallo,\n\n{% if delegatorName %}{{ delegatorName }}{% else %}ein "
    "Mitglied{% endif %} hat dich für die Sitzung „{{ meetingTitle }}“"
    "{% if gremiumName %} ({{ gremiumName }}){% endif %}"
    "{% if meetingDate %} am {{ meetingDate }}{% endif %} als Vertretung "
    "eingetragen{% if voting %} — inklusive Stimmrecht{% endif %}.\n",
    "en": "Hello,\n\n{% if delegatorName %}{{ delegatorName }}{% else %}a "
    "member{% endif %} registered you as proxy for the meeting "
    '"{{ meetingTitle }}"{% if gremiumName %} ({{ gremiumName }}){% endif %}'
    "{% if meetingDate %} on {{ meetingDate }}{% endif %}"
    "{% if voting %} — including the voting right{% endif %}.\n",
}
BUILTIN_DELEGATION_REVOKED_SUBJECT = {
    "de": "Vertretung widerrufen: {{ meetingTitle }}",
    "en": "Proxy revoked: {{ meetingTitle }}",
}
BUILTIN_DELEGATION_REVOKED_BODY = {
    "de": "Hallo,\n\ndeine Vertretung für die Sitzung „{{ meetingTitle }}“"
    "{% if gremiumName %} ({{ gremiumName }}){% endif %}"
    "{% if meetingDate %} am {{ meetingDate }}{% endif %} wurde widerrufen.\n",
    "en": 'Hello,\n\nyour proxy for the meeting "{{ meetingTitle }}"'
    "{% if gremiumName %} ({{ gremiumName }}){% endif %}"
    "{% if meetingDate %} on {{ meetingDate }}{% endif %} was revoked.\n",
}

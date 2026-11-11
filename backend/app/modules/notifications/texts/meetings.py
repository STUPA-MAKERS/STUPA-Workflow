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

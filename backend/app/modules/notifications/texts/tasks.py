"""Builtin texts of the task mails.

The mail catalogue reads them for the template editor. The sender is in
`flow.mail_actions` and uses the same objects as its fallback.
"""

from __future__ import annotations

BUILTIN_TASK_SUBJECT = {
    "de": "Neue Aufgabe: Antrag{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": 'New task: application{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
}
BUILTIN_TASK_BODY = {
    "de": "Hallo,\n\nder Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} hat einen "
    "Schritt erreicht, in dem du handeln kannst"
    "{% if status %} (Status: {{ status }}){% endif %}.\n",
    "en": "Hello,\n\nthe application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} reached a '
    "step where you can act"
    "{% if status %} (status: {{ status }}){% endif %}.\n",
}

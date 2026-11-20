"""Builtin texts of the mail about a changed approved amount (spec 001621).

The mail catalogue reads them for the template editor. The sender is in
`applications.amend_mail` and uses the same objects as its fallback.
"""

from __future__ import annotations

AMOUNT_CHANGED_KEY = "approved_amount_changed"
#: The kind of the opt-out: the mail tells the applicant about the own application.
AMOUNT_CHANGED_KIND = "status_update"

AMOUNT_CHANGED_SUBJECT = {
    "de": "Genehmigter Betrag geändert"
    "{% if applicationTitle %}: „{{ applicationTitle }}“{% endif %}",
    "en": "Approved amount changed"
    '{% if applicationTitle %}: "{{ applicationTitle }}"{% endif %}',
}
AMOUNT_CHANGED_BODY = {
    "de": "Hallo,\n\nder genehmigte Betrag Ihres Antrags"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} wurde geändert."
    "\n\nBisher: {{ previousAmount }}\nNeu: {{ approvedAmount }}"
    "{% if gremium %}\n\nGrundlage ist der Beschluss von {{ gremium }}"
    "{% if decisionDate %} vom {{ decisionDate }}{% endif %}.{% endif %}\n",
    "en": "Hello,\n\nthe approved amount of your application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} has changed.'
    "\n\nBefore: {{ previousAmount }}\nNew: {{ approvedAmount }}"
    "{% if gremium %}\n\nIt rests on the decision of {{ gremium }}"
    "{% if decisionDate %} of {{ decisionDate }}{% endif %}.{% endif %}\n",
}

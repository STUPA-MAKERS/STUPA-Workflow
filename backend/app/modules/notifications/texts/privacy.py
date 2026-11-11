"""Builtin texts of the erasure mails.

The mail catalogue reads them for the template editor. The senders are in
`applications.erasure_mail` and `privacy.mails` and use the same
objects as their fallback.
"""

from __future__ import annotations

ERASURE_REQUESTED_SUBJECT: dict[str, str] = {
    "de": "Neuer Löschantrag (DSGVO Art. 17)",
    "en": "New erasure request (GDPR Art. 17)",
}
ERASURE_REQUESTED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nein Löschantrag ist eingegangen und wartet auf Bearbeitung in "
    "der Datenschutz-Verwaltung.\n",
    "en": "Hello,\n\nan erasure request has been received and is awaiting review in "
    "the privacy admin area.\n",
}
ERASURE_EXECUTED_SUBJECT: dict[str, str] = {
    "de": "Ihre Daten wurden gelöscht (DSGVO Art. 17)",
    "en": "Your data has been erased (GDPR Art. 17)",
}
ERASURE_EXECUTED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nIhr Löschantrag wurde ausgeführt. Ihre personenbezogenen Daten "
    "wurden gemäß DSGVO Art. 17 anonymisiert bzw. gelöscht.\n",
    "en": "Hello,\n\nyour erasure request has been executed. Your personal data has "
    "been anonymised or erased in accordance with GDPR Art. 17.\n",
}
ERASURE_REJECTED_SUBJECT: dict[str, str] = {
    "de": "Ihr Löschantrag wurde abgelehnt",
    "en": "Your erasure request was rejected",
}
ERASURE_REJECTED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nIhr Löschantrag wurde abgelehnt{% if reason %}: {{ reason }}{% endif %}.\n",
    "en": "Hello,\n\nyour erasure request was rejected{% if reason %}: {{ reason }}{% endif %}.\n",
}

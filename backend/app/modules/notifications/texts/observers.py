"""Builtin texts of the mails to the observers of an application.

The mail catalogue reads them for the template editor. The sender is in
`applications.observer_mails` and uses the same objects as its fallback.
"""

from __future__ import annotations

#: The template key and the footer kind of the mail after an add.
OBSERVER_ADDED_KEY = "application_observer_added"
#: The template key of the status mail to an observer. Its kind is ``status_update``,
#: so an account that switched the status mails off gets none.
OBSERVER_STATUS_KEY = "application_observer_status"

OBSERVER_ADDED_SUBJECT: dict[str, str] = {
    "de": "Du beobachtest einen Antrag"
    "{% if applicationTitle %}: „{{ applicationTitle }}“{% endif %}",
    "en": "You observe an application"
    '{% if applicationTitle %}: "{{ applicationTitle }}"{% endif %}',
}
OBSERVER_ADDED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n"
    "{% if applicantName %}{{ applicantName }}{% else %}Die antragstellende Person{% endif %} "
    "hat dich als Beobachter:in zum Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} hinzugefügt. "
    "Du kannst den Status und den Verlauf lesen und bekommst eine Mail bei jedem neuen "
    "Status.\n\n"
    "Mit diesem Link meldest du dich an:\n{{ link }}\n\n"
    "Hast du ein Konto mit dieser Adresse, findest du den Antrag auch nach der Anmeldung "
    "unter „Anträge“.\n\n"
    "Du willst den Antrag nicht beobachten? Dann beende die Beobachtung hier:\n{{ endLink }}\n",
    "en": "Hello,\n\n"
    "{% if applicantName %}{{ applicantName }}{% else %}The applicant{% endif %} "
    "added you as an observer of the application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}. '
    "You can read its status and history and get a mail for each new status.\n\n"
    "Sign in with this link:\n{{ link }}\n\n"
    "If you have an account with this address, you also find the application under "
    '"Applications" after the login.\n\n'
    "You do not want to observe the application? End the observation here:\n{{ endLink }}\n",
}
OBSERVER_ADDED_PLACEHOLDERS: dict[str, str] = {
    "applicationTitle": "Titel des Antrags",
    "applicantName": "Name der antragstellenden Person",
    "link": "Login-Link der Adresse",
    "endLink": "Link, der die Beobachtung beendet",
    "applicationId": "ID des Antrags",
}

OBSERVER_STATUS_SUBJECT: dict[str, str] = {
    "de": "Neuer Status: Antrag{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": 'New status: application{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
}
OBSERVER_STATUS_BODY: dict[str, str] = {
    "de": "Hallo,\n\n"
    "der Antrag{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}, den du "
    "beobachtest, hat einen neuen Status{% if status %}: {{ status }}{% endif %}.\n\n"
    "Hier liest du den Antrag:\n{{ link }}\n\n"
    "Du willst den Antrag nicht mehr beobachten? Dann beende die Beobachtung hier:\n"
    "{{ endLink }}\n",
    "en": "Hello,\n\n"
    'the application{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} that '
    "you observe has a new status{% if status %}: {{ status }}{% endif %}.\n\n"
    "Read the application here:\n{{ link }}\n\n"
    "You do not want to observe the application any more? End the observation here:\n"
    "{{ endLink }}\n",
}
OBSERVER_STATUS_PLACEHOLDERS: dict[str, str] = {
    "applicationTitle": "Titel des Antrags",
    "status": "Neuer Status",
    "link": "Link zum Antrag",
    "endLink": "Link, der die Beobachtung beendet",
    "applicationId": "ID des Antrags",
}

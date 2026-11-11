"""Builtin texts of the captured-Antrag mails.

The mail catalogue reads them for the template editor. The sender is in
`applications.captured_mail` and uses the same objects as its fallback.
"""

from __future__ import annotations

#: The template key and the footer kind of the mail.
APPLICATION_CAPTURED_KEY = "application_captured"

APPLICATION_CAPTURED_SUBJECT: dict[str, str] = {
    "de": "Für dich wurde ein Antrag erfasst"
    "{% if applicationTitle %}: „{{ applicationTitle }}“{% endif %}",
    "en": "An application was entered for you"
    '{% if applicationTitle %}: "{{ applicationTitle }}"{% endif %}',
}
APPLICATION_CAPTURED_BODY: dict[str, str] = {
    "de": "Hallo{% if applicantName %} {{ applicantName }}{% endif %},\n\n"
    "für dich wurde ein Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} "
    "auf der Antragsplattform erfasst"
    "{% if gremiumName %} ({{ gremiumName }}){% endif %}."
    "{% if receivedOn %} Eingegangen am {{ receivedOn }}.{% endif %}"
    "{% if intake %} Eingang: {{ intake }}.{% endif %}\n\n"
    "Der Antrag gehört dir. Du kannst ihn hier ansehen und verfolgen:\n{{ link }}\n"
    "{% if isGuest %}\nDer Link ist dein persönlicher Zugang. Gib ihn nicht weiter.\n"
    "{% else %}\nMelde dich mit deinem Konto an, um den Antrag zu öffnen.\n{% endif %}",
    "en": "Hello{% if applicantName %} {{ applicantName }}{% endif %},\n\n"
    "an application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} '
    "was entered for you on the application platform"
    "{% if gremiumName %} ({{ gremiumName }}){% endif %}."
    "{% if receivedOn %} Received on {{ receivedOn }}.{% endif %}"
    "{% if intake %} Intake: {{ intake }}.{% endif %}\n\n"
    "The application is yours. You can view and follow it here:\n{{ link }}\n"
    "{% if isGuest %}\nThe link is your personal access. Do not share it.\n"
    "{% else %}\nSign in with your account to open the application.\n{% endif %}",
}

#: The placeholders of the template editor.
APPLICATION_CAPTURED_PLACEHOLDERS: dict[str, str] = {
    "applicationTitle": "Titel des Antrags",
    "applicantName": "Name der antragstellenden Person",
    "gremiumName": "Gremium des Antrags",
    "receivedOn": "Eingangsdatum",
    "intake": "Eingang (zum Beispiel „per PDF“)",
    "link": "Link zum Antrag (Konto) oder Zugangslink (Gast)",
    "isGuest": "Wahr bei einem Gast ohne Konto",
    "applicationId": "ID des Antrags",
}

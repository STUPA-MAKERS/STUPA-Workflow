"""Builtin texts of the comment mails.

The mail catalogue reads them for the template editor. The sender is in
`applications.comment_mails` and uses the same objects as its fallback.
"""

from __future__ import annotations

APPLICANT_TEMPLATE_KEY = "comment_applicant"
TEAM_TEMPLATE_KEY = "comment_team"

BUILTIN_APPLICANT_SUBJECT = {
    "de": "Neuer Kommentar zu Ihrem Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": "New comment on your application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
}
BUILTIN_APPLICANT_BODY = {
    "de": "Hallo,\n\nzu Ihrem Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} "
    "gibt es einen neuen Kommentar"
    "{% if commentAuthor %} von {{ commentAuthor }}{% endif %}:"
    "\n\n{{ comment }}\n",
    "en": "Hello,\n\nthere is a new comment on your application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}'
    "{% if commentAuthor %} from {{ commentAuthor }}{% endif %}:"
    "\n\n{{ comment }}\n",
}
BUILTIN_TEAM_SUBJECT = {
    "de": "Rückfrage zum Antrag{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": 'Applicant comment on{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
}
BUILTIN_TEAM_BODY = {
    "de": "Hallo,\n\nder/die Antragsteller:in hat den Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} kommentiert"
    "{% if status %} (aktueller Status: {{ status }}){% endif %}:"
    "\n\n{{ comment }}\n",
    "en": "Hello,\n\nthe applicant commented on the application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}'
    "{% if status %} (current status: {{ status }}){% endif %}:"
    "\n\n{{ comment }}\n",
}

COMMENT_EXCERPT_LEN = 1000

#: Chat bubble of the HTML mail, as the web UI shows a message of another person:
#: initials avatar, author name, gray left-aligned bubble. Jinja renders it with
#: autoescape; the ``| e ... | safe`` chain turns only the inserted ``<br>`` into markup,
#: so the comment text stays escaped.
CHAT_BUBBLE_HTML = (
    '<table role="presentation" cellpadding="0" cellspacing="0"'
    ' style="margin:16px 0 0;">'
    "<tr>"
    '<td style="vertical-align:top;padding-right:8px;">'
    '<div style="width:28px;height:28px;border-radius:50%;background:#e5e9f0;'
    "color:#6b7686;font-size:11px;font-weight:600;text-align:center;"
    'line-height:28px;">{{ commentAuthorInitials }}</div>'
    "</td>"
    '<td style="vertical-align:top;">'
    '<div style="font-size:12px;color:#6b7686;margin:0 0 3px;">'
    '<strong style="color:#1f2933;">{{ commentAuthor }}</strong></div>'
    '<div style="background:#eef1f5;border-radius:0 12px 12px 12px;'
    'padding:8px 12px;font-size:14px;line-height:1.5;color:#1f2933;">'
    "{{ comment | e | replace('\\n', '<br>' | safe) }}</div>"
    "</td>"
    "</tr>"
    "</table>"
)

BUILTIN_APPLICANT_BODY_HTML = {
    "de": '<p style="margin:0 0 1em;">Hallo,</p>'
    '<p style="margin:0;">zu Ihrem Antrag'
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} "
    "gibt es einen neuen Kommentar:</p>" + CHAT_BUBBLE_HTML,
    "en": '<p style="margin:0 0 1em;">Hello,</p>'
    '<p style="margin:0;">there is a new comment on your application'
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}:</p>' + CHAT_BUBBLE_HTML,
}
BUILTIN_TEAM_BODY_HTML = {
    "de": '<p style="margin:0 0 1em;">Hallo,</p>'
    '<p style="margin:0;">der/die Antragsteller:in hat den Antrag'
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} kommentiert"
    "{% if status %} (aktueller Status: {{ status }}){% endif %}:</p>" + CHAT_BUBBLE_HTML,
    "en": '<p style="margin:0 0 1em;">Hello,</p>'
    '<p style="margin:0;">the applicant commented on the application'
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}'
    "{% if status %} (current status: {{ status }}){% endif %}:</p>" + CHAT_BUBBLE_HTML,
}

#: Author label of an applicant comment without a known display name.
APPLICANT_AUTHOR_FALLBACK = {"de": "Antragsteller:in", "en": "Applicant"}
#: Author label of a member comment on an application without a Gremium (as in the UI).
COMMITTEE_AUTHOR_FALLBACK = {"de": "Gremium", "en": "Committee"}

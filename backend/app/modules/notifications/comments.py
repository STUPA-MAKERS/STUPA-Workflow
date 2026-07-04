"""Comment notifications.

Two directions, depending on the comment author:

* **Principal comments publicly** → mail to the applicant address (internal
  comments deliberately trigger NOTHING — applicants never see them).
* **Applicant comments** → mail to everyone who can act at the current state
  (task semantics): for ``vote`` states the members of the voting committee,
  otherwise exactly the principals for whom at least one manual
  ``requires_action`` transition is actually firable.

Both paths respect the ``comment`` kind opt-out and use the DB templates
``comment_applicant``/``comment_team`` (builtin fallback). Called as a
background task after the comment response (own session).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.flow.models import State
from app.modules.notifications.mail import MailMessage, compute_idempotency_key
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import actionable_principal_emails
from app.modules.notifications.service import (
    NotificationService,
    filter_recipients_by_preference,
)
from app.modules.notifications.templating import (
    TemplateRenderError,
    render_mail,
)
from app.settings import Settings

logger = logging.getLogger("app.notifications")

APPLICANT_TEMPLATE_KEY = "comment_applicant"
TEAM_TEMPLATE_KEY = "comment_team"

_BUILTIN_APPLICANT_SUBJECT = {
    "de": "Neuer Kommentar zu Ihrem Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": "New comment on your application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
}
_BUILTIN_APPLICANT_BODY = {
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
_BUILTIN_TEAM_SUBJECT = {
    "de": "Rückfrage zum Antrag{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": 'Applicant comment on{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
}
_BUILTIN_TEAM_BODY = {
    "de": "Hallo,\n\nder/die Antragsteller:in hat den Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} kommentiert"
    "{% if status %} (aktueller Status: {{ status }}){% endif %}:"
    "\n\n{{ comment }}\n",
    "en": "Hello,\n\nthe applicant commented on the application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}'
    "{% if status %} (current status: {{ status }}){% endif %}:"
    "\n\n{{ comment }}\n",
}

_COMMENT_EXCERPT_LEN = 1000

# --- Stylized chat message for the HTML mail (mirrors the web-UI chat) ------ #
# One shared bubble snippet: avatar with initials, author name, gray
# left-aligned bubble — the same look as a foreign message in the web UI.
# Rendered with Jinja autoescape; `| e … | safe` only turns the *inserted*
# ``<br>`` into markup, the comment text itself stays escaped.
_CHAT_BUBBLE_HTML = (
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

_BUILTIN_APPLICANT_BODY_HTML = {
    "de": '<p style="margin:0 0 1em;">Hallo,</p>'
    '<p style="margin:0;">zu Ihrem Antrag'
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} "
    "gibt es einen neuen Kommentar:</p>" + _CHAT_BUBBLE_HTML,
    "en": '<p style="margin:0 0 1em;">Hello,</p>'
    '<p style="margin:0;">there is a new comment on your application'
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}:</p>' + _CHAT_BUBBLE_HTML,
}
_BUILTIN_TEAM_BODY_HTML = {
    "de": '<p style="margin:0 0 1em;">Hallo,</p>'
    '<p style="margin:0;">der/die Antragsteller:in hat den Antrag'
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} kommentiert"
    "{% if status %} (aktueller Status: {{ status }}){% endif %}:</p>" + _CHAT_BUBBLE_HTML,
    "en": '<p style="margin:0 0 1em;">Hello,</p>'
    '<p style="margin:0;">the applicant commented on the application'
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}'
    "{% if status %} (current status: {{ status }}){% endif %}:</p>" + _CHAT_BUBBLE_HTML,
}

# Fallback author label when no display name is known (applicant comments).
_APPLICANT_AUTHOR_FALLBACK = {"de": "Antragsteller:in", "en": "Applicant"}


def _initials(name: str) -> str:
    """Initial(s) for the mail avatar — same rule as the web-UI chat."""
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    first = parts[0][0]
    last = parts[-1][0] if len(parts) > 1 else ""
    return (first + last).upper()


async def send_comment_notifications(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    application_id: uuid.UUID,
    comment_id: uuid.UUID,
    author_kind: str,
    visibility: str,
    body: str,
    author_name: str | None = None,
) -> int:
    """Send comment mails; returns the number of mail jobs."""
    app_row = (
        await session.execute(
            select(
                Application.data,
                Application.current_state_id,
            ).where(Application.id == application_id)
        )
    ).first()
    if app_row is None:
        return 0
    data, state_id = app_row
    title = (data or {}).get("title")
    service = NotificationService(session, queue=queue, settings=settings)

    state = await session.get(State, state_id) if state_id is not None else None
    status_label = ""
    if state is not None and isinstance(state.label_i18n, dict) and state.label_i18n:
        status_label = state.label_i18n.get(settings.mail_default_lang) or next(
            iter(state.label_i18n.values())
        )

    # Author label for the chat bubble: display name, else the localized
    # applicant fallback (matches the web-UI author fallback).
    author_label = (author_name or "").strip()
    if not author_label:
        author_label = _APPLICANT_AUTHOR_FALLBACK.get(
            settings.mail_default_lang, _APPLICANT_AUTHOR_FALLBACK["de"]
        )

    context = {
        "applicationId": str(application_id),
        "applicationTitle": title.strip() if isinstance(title, str) else "",
        "status": status_label,
        "comment": body[:_COMMENT_EXCERPT_LEN],
        "commentAuthor": author_label,
        "commentAuthorInitials": _initials(author_label),
    }

    if author_kind == "principal":
        # Internal comments are invisible to applicants → no mail.
        if visibility != "public":
            return 0
        recipients = await service.resolver.resolve(
            [{"kind": "applicant"}], application_id=application_id
        )
        template_key = APPLICANT_TEMPLATE_KEY
        builtin = (
            _BUILTIN_APPLICANT_SUBJECT,
            _BUILTIN_APPLICANT_BODY,
            _BUILTIN_APPLICANT_BODY_HTML,
        )
    else:
        recipients = await actionable_principal_emails(
            session, application_id=application_id, state=state
        )
        template_key = TEAM_TEMPLATE_KEY
        builtin = (_BUILTIN_TEAM_SUBJECT, _BUILTIN_TEAM_BODY, _BUILTIN_TEAM_BODY_HTML)

    recipients = await filter_recipients_by_preference(session, recipients, "comment")
    if not recipients:
        logger.info("comment notification resolved no recipients — skipped")
        return 0

    idem = ("comment", str(comment_id), template_key)
    tpl = await service._get_template_by_key(template_key)  # noqa: SLF001
    if tpl is not None:
        ok = await service._render_and_enqueue(  # noqa: SLF001
            tpl,
            recipients,
            context=context,
            lang=None,
            idempotency_parts=idem,
            reason="comment",
        )
        return int(ok)
    try:
        rendered = render_mail(
            subject_i18n=builtin[0],
            body_i18n=builtin[1],
            body_html_i18n=builtin[2],
            context=context,
            lang=settings.mail_default_lang,
            default_lang=settings.mail_default_lang,
        )
    except TemplateRenderError as exc:  # defensive — builtin covers all vars
        logger.warning("comment builtin render failed: %s", exc)
        return 0
    msg = MailMessage(
        to=tuple(recipients),
        subject=rendered.subject,
        text=rendered.text,
        html=service._layout_html(rendered, "comment"),  # noqa: SLF001
        idempotency_key=compute_idempotency_key(*idem),
    )
    return int(await service._enqueue(msg))  # noqa: SLF001

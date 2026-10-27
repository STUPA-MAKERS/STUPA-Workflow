"""Comment notifications.

The author of the comment decides the direction.

A comment with files and no text uses the file names, joined by ", ", as its text
(``comment_mail_text``). A mail never carries a file or a download link.

A public comment from a principal sends a mail to the applicant address. An
internal comment deliberately sends nothing. Applicants never see an internal
comment.

A comment from the applicant sends a mail to everyone who can act at the
current state (task semantics). For a `vote` state these are the members of the
voting Gremium. For any other state these are exactly the principals that can
fire at least one manual `requires_action` transition.

The mail to the applicant names the Gremium of the application as the author, not
the member. This matches the applicant view of the comment list. Only
the mail to the team keeps a display name.

Both paths respect the opt-out of the `comment` kind. Both use the DB templates
`comment_applicant` and `comment_team`, with a builtin fallback. The caller runs
this as a background task with its own session after the comment response.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.applications.service.service_base import gremium_actor_name
from app.modules.flow.models import State
from app.modules.notifications.layout import append_link_text
from app.modules.notifications.links import application_link
from app.modules.notifications.mail import MailMessage, compute_idempotency_key
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import actionable_principal_emails
from app.modules.notifications.service import (
    NotificationService,
    filter_recipients_by_preference,
    resolve_application_lang,
)
from app.modules.notifications.templating import (
    TemplateRenderError,
    render_mail,
)
from app.settings import Settings
from app.shared.i18n import pick_lang, resolve_i18n

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

#: Chat bubble of the HTML mail, as the web UI shows a message of another person:
#: initials avatar, author name, gray left-aligned bubble. Jinja renders it with
#: autoescape; the ``| e ... | safe`` chain turns only the inserted ``<br>`` into markup,
#: so the comment text stays escaped.
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

#: Author label of an applicant comment without a known display name.
_APPLICANT_AUTHOR_FALLBACK = {"de": "Antragsteller:in", "en": "Applicant"}
#: Author label of a member comment on an application without a Gremium (as in the UI).
_COMMITTEE_AUTHOR_FALLBACK = {"de": "Gremium", "en": "Committee"}


def comment_mail_text(body: str, filenames: list[str]) -> str:
    """Return the text of a comment mail: the body, or the file names without one."""
    if body.strip() or not filenames:
        return body
    return ", ".join(filenames)


def _initials(name: str) -> str:
    """Return the initials for the mail avatar (same rule as the web-UI chat)."""
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
    """Send the comment mails.

    The function uses ``author_name`` only for the mail to the team. The mail to
    the applicant names the Gremium of the application instead.

    Returns:
        The number of mail jobs that went to the queue.

    An internal member comment sends no mail at all, because applicants never see it; the
    check comes first, because it makes every other read pointless. The applicant gets the
    mail in the language of the application, the team in the configured default. The
    applicant never sees a member name: a member comment names the Gremium, an applicant
    comment keeps the display name or the localized fallback, as in the web UI. The link
    opens the comments at this comment: for a guest the public applicant page, for an
    account and for the team the application.
    """
    app_row = (
        await session.execute(
            select(
                Application.data,
                Application.current_state_id,
                Application.gremium_id,
                Application.created_by,
            ).where(Application.id == application_id)
        )
    ).first()
    if app_row is None:
        return 0
    data, state_id, gremium_id, created_by = app_row
    if author_kind == "principal" and visibility != "public":
        return 0
    title = (data or {}).get("title")
    service = NotificationService(session, queue=queue, settings=settings)

    lang = (
        await resolve_application_lang(
            session, application_id=application_id, settings=settings
        )
        if author_kind == "principal"
        else settings.mail_default_lang
    )

    state = await session.get(State, state_id) if state_id is not None else None
    status_label = ""
    if state is not None and isinstance(state.label_i18n, dict) and state.label_i18n:
        status_label = resolve_i18n(state.label_i18n, lang) or ""

    if author_kind == "principal":
        author_label = (await gremium_actor_name(session, gremium_id) or "").strip()
        fallback = _COMMITTEE_AUTHOR_FALLBACK
    else:
        author_label = (author_name or "").strip()
        fallback = _APPLICANT_AUTHOR_FALLBACK
    if not author_label:
        author_label = pick_lang(fallback, lang)

    link = application_link(
        settings,
        application_id,
        guest=author_kind == "principal" and created_by is None,
        comment_id=comment_id,
    )
    context: dict[str, object] = {
        "link": link.url,
        "applicationId": str(application_id),
        "applicationTitle": title.strip() if isinstance(title, str) else "",
        "status": status_label,
        "comment": body[:_COMMENT_EXCERPT_LEN],
        "commentAuthor": author_label,
        "commentAuthorInitials": _initials(author_label),
    }

    if author_kind == "principal":
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
    tpl = await service._get_template_by_key(template_key)
    if tpl is not None:
        ok = await service._render_and_enqueue(
            tpl,
            recipients,
            context=context,
            lang=lang,
            idempotency_parts=idem,
            reason="comment",
            link=link,
        )
        return int(ok)
    try:
        rendered = render_mail(
            subject_i18n=builtin[0],
            body_i18n=builtin[1],
            body_html_i18n=builtin[2],
            context=context,
            lang=lang,
            default_lang=settings.mail_default_lang,
        )
    except TemplateRenderError as exc:
        logger.warning("comment builtin render failed: %s", exc)
        return 0
    msg = MailMessage(
        to=tuple(recipients),
        subject=rendered.subject,
        text=append_link_text(rendered.text, link.url, link.label(rendered.lang)),
        html=service._layout_html(rendered, "comment", link),
        idempotency_key=compute_idempotency_key(*idem),
    )
    return int(await service._enqueue(msg))

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

from app.modules.applications.mail_data import application_specs, resolve_application_lang
from app.modules.applications.models import Application
from app.modules.applications.service.service_base import gremium_actor_name
from app.modules.flow.actionable import actionable_principal_emails
from app.modules.flow.models import State
from app.modules.notifications.chat_mail import initials
from app.modules.notifications.layout import append_link_text
from app.modules.notifications.links import application_link
from app.modules.notifications.mail import MailMessage, compute_idempotency_key
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService, filter_recipients_by_preference
from app.modules.notifications.templating import (
    TemplateRenderError,
    render_mail,
)
from app.modules.notifications.texts.comments import (
    APPLICANT_AUTHOR_FALLBACK,
    APPLICANT_TEMPLATE_KEY,
    BUILTIN_APPLICANT_BODY,
    BUILTIN_APPLICANT_BODY_HTML,
    BUILTIN_APPLICANT_SUBJECT,
    BUILTIN_TEAM_BODY,
    BUILTIN_TEAM_BODY_HTML,
    BUILTIN_TEAM_SUBJECT,
    COMMENT_EXCERPT_LEN,
    COMMITTEE_AUTHOR_FALLBACK,
    TEAM_TEMPLATE_KEY,
)
from app.settings import Settings
from app.shared.i18n import pick_lang, resolve_i18n

logger = logging.getLogger("app.notifications")


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
    service = NotificationService(
        session, queue=queue, settings=settings, expand_specs=application_specs
    )
    to_applicant = author_kind == "principal"

    lang = (
        await resolve_application_lang(session, application_id=application_id, settings=settings)
        if to_applicant
        else settings.mail_default_lang
    )

    state = await session.get(State, state_id) if state_id is not None else None
    labels = state.label_i18n if state is not None else None
    status_label = (resolve_i18n(labels, lang) or "") if isinstance(labels, dict) and labels else ""

    named_author = (
        (await gremium_actor_name(session, gremium_id) or "")
        if to_applicant
        else (author_name or "")
    ).strip()
    fallback = COMMITTEE_AUTHOR_FALLBACK if to_applicant else APPLICANT_AUTHOR_FALLBACK
    author_label = named_author or pick_lang(fallback, lang)

    link = application_link(
        settings,
        application_id,
        guest=to_applicant and created_by is None,
        comment_id=comment_id,
    )
    context: dict[str, object] = {
        "link": link.url,
        "applicationId": str(application_id),
        "applicationTitle": title.strip() if isinstance(title, str) else "",
        "status": status_label,
        "comment": body[:COMMENT_EXCERPT_LEN],
        "commentAuthor": author_label,
        "commentAuthorInitials": initials(author_label),
    }

    resolved = (
        await service.resolver.resolve([{"kind": "applicant"}], application_id=application_id)
        if to_applicant
        else await actionable_principal_emails(session, application_id=application_id, state=state)
    )
    template_key = APPLICANT_TEMPLATE_KEY if to_applicant else TEAM_TEMPLATE_KEY
    builtin = (
        (BUILTIN_APPLICANT_SUBJECT, BUILTIN_APPLICANT_BODY, BUILTIN_APPLICANT_BODY_HTML)
        if to_applicant
        else (BUILTIN_TEAM_SUBJECT, BUILTIN_TEAM_BODY, BUILTIN_TEAM_BODY_HTML)
    )

    recipients = await filter_recipients_by_preference(session, resolved, "comment")
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

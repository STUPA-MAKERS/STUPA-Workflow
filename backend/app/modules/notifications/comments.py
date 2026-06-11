"""Kommentar-Benachrichtigungen (#4-1).

Zwei Richtungen, je nach Autor des Kommentars:

* **Principal kommentiert öffentlich** → Mail an die Antragsteller-Adresse
  (interne Kommentare lösen bewusst NICHTS aus — Antragsteller sehen sie nie).
* **Antragsteller kommentiert** → Mail an alle, die am aktuellen State handeln
  können (Task-Semantik, #64): bei ``vote``-States die Mitglieder des
  abstimmenden Gremiums, sonst Inhaber:innen einer Rolle mit
  ``application.transition`` (global oder im Gremium des Antrags) sowie Admins.

Beide Wege respektieren die Abwahl der Art ``comment`` (#4-2) und nutzen die
DB-Templates ``comment_applicant``/``comment_team`` (Builtin-Fallback).
Aufruf erfolgt als Background-Task nach der Kommentar-Antwort (eigene Session).
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
    "gibt es einen neuen Kommentar:\n\n{{ comment }}\n",
    "en": "Hello,\n\nthere is a new comment on your application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}:'
    "\n\n{{ comment }}\n",
}
_BUILTIN_TEAM_SUBJECT = {
    "de": "Rückfrage zum Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": "Applicant comment on"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
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
) -> int:
    """Kommentar-Mails versenden (#4-1); gibt die Zahl der Mail-Jobs zurück."""
    app_row = (
        await session.execute(
            select(
                Application.data,
                Application.current_state_id,
                Application.gremium_id,
            ).where(Application.id == application_id)
        )
    ).first()
    if app_row is None:
        return 0
    data, state_id, gremium_id = app_row
    title = (data or {}).get("title")
    service = NotificationService(session, queue=queue, settings=settings)

    state = await session.get(State, state_id) if state_id is not None else None
    status_label = ""
    if state is not None and isinstance(state.label_i18n, dict) and state.label_i18n:
        status_label = state.label_i18n.get(settings.mail_default_lang) or next(
            iter(state.label_i18n.values())
        )

    context = {
        "applicationId": str(application_id),
        "applicationTitle": title.strip() if isinstance(title, str) else "",
        "status": status_label,
        "comment": body[:_COMMENT_EXCERPT_LEN],
    }

    if author_kind == "principal":
        # Interne Kommentare sind für Antragsteller unsichtbar → keine Mail.
        if visibility != "public":
            return 0
        recipients = await service.resolver.resolve(
            [{"kind": "applicant"}], application_id=application_id
        )
        template_key = APPLICANT_TEMPLATE_KEY
        builtin = (_BUILTIN_APPLICANT_SUBJECT, _BUILTIN_APPLICANT_BODY)
    else:
        recipients = await actionable_principal_emails(
            session, state=state, gremium_id=gremium_id
        )
        template_key = TEAM_TEMPLATE_KEY
        builtin = (_BUILTIN_TEAM_SUBJECT, _BUILTIN_TEAM_BODY)

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
            context=context,
            lang=settings.mail_default_lang,
            default_lang=settings.mail_default_lang,
        )
    except TemplateRenderError as exc:  # defensiv — Builtin deckt alle Vars
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

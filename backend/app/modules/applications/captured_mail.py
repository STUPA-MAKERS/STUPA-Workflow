"""The mail to the applicant of an application captured on their behalf.

A person with ``application.create_on_behalf`` entered the application. The applicant
gets one mail with a link:

- An applicant account gets the normal link to the application
  (``/applications/{id}``). The login is the usual one.
- A guest applicant gets the login link of the e-mail login
  (``/my-applications#t=…``), as after a guest submission. The link comes from
  ``auth.email_login.issue_confirm_link``, so the token rules are the same.

The mail is not opt-outable: its kind is not in ``NOTIFICATION_KINDS``, like the magic
link. It is the only notice that an application in the name of the person exists.

The send runs as a background task after the commit, in its own session. It is best
effort: a failure logs and never breaks the request.
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.db import get_sessionmaker
from app.modules.applications.mail_data import resolve_application_lang
from app.modules.notifications.links import MailLink
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.captured import (
    APPLICATION_CAPTURED_BODY,
    APPLICATION_CAPTURED_KEY,
    APPLICATION_CAPTURED_SUBJECT,
)
from app.settings import Settings

logger = logging.getLogger("app.notifications")


def _format_date(value: date | None, lang: str) -> str:
    """Return the date as ``05.10.2026`` (de) or ``2026-10-05`` (en)."""
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y") if lang == "de" else value.isoformat()


async def notify_application_captured(
    *,
    queue: MailQueue | None,
    settings: Settings,
    application_id: UUID,
    email: str,
    guest: bool,
) -> None:
    """Send the mail to the applicant of a captured application.

    ``guest`` selects the link: the e-mail login link for a guest, the normal link for an
    account. The idempotency key holds only the application, so a retry or a second
    call for the same application coalesces into one mail.
    """
    from app.modules.applications.models import Applicant, Application
    from app.modules.auth import email_login
    from app.modules.gremien.models import Gremium

    try:
        async with get_sessionmaker()() as session:
            app = await session.get(Application, application_id)
            if app is None:
                return
            name = await session.scalar(
                select(Applicant.name).where(Applicant.application_id == application_id)
            )
            gremium = await session.get(Gremium, app.gremium_id) if app.gremium_id else None
            lang = await resolve_application_lang(
                session, application_id=application_id, settings=settings
            )
            title = app.data.get("title") if isinstance(app.data, dict) else None
            context: dict[str, object] = {
                "applicationTitle": str(title) if title else "",
                "applicantName": name or "",
                "gremiumName": gremium.name if gremium is not None else "",
                "receivedOn": _format_date(app.received_on, lang),
                "intake": app.capture_intake or "",
                "isGuest": guest,
                "applicationId": str(application_id),
            }
            service = NotificationService(session, queue=queue, settings=settings)

            async def deliver(recipient: str, link: str) -> None:
                await service.send_kind_mail(
                    [recipient],
                    kind=APPLICATION_CAPTURED_KEY,
                    template_key=APPLICATION_CAPTURED_KEY,
                    builtin_subject=APPLICATION_CAPTURED_SUBJECT,
                    builtin_body=APPLICATION_CAPTURED_BODY,
                    context={**context, "link": link},
                    idempotency_parts=(APPLICATION_CAPTURED_KEY, str(application_id)),
                    lang=lang,
                    link=MailLink(link, "application"),
                )

            if guest:
                link = await email_login.issue_confirm_link(session, settings, email=email)
                await deliver(email, link)
                await session.commit()
            else:
                base = settings.public_base_url.rstrip("/")
                await deliver(email, f"{base}/applications/{application_id}")
    except Exception:
        logger.exception("application_captured mail failed (application=%s)", application_id)

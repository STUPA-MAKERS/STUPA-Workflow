"""The mails to the observers of an application.

- After an add the observer gets one mail with the login link of the e-mail login
  (`email_login.issue_confirm_link`) and the end link. Its kind is not in
  ``NOTIFICATION_KINDS``, so nobody can switch it off: it is the only notice of the add.
- Each status mail that goes to the applicant also goes to every observer, as one mail
  per observer, because each mail carries the own end link. Its kind is
  ``status_update``, so an account that switched the status mails off gets none.

The link of a status mail opens ``/applications/{id}`` for an address of an active
account and ``/my-applications/{id}`` for every other address. Both sends are best
effort: a failure logs and never breaks the request or the flow (the router guards the
mail after an add, the flow guards the status mails).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.mail_data import resolve_application_lang
from app.modules.applications.models import Applicant, Application, ApplicationObserver
from app.modules.applications.observers import end_link, list_observers
from app.modules.notifications.links import MailLink, application_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.observers import (
    OBSERVER_ADDED_BODY,
    OBSERVER_ADDED_KEY,
    OBSERVER_ADDED_SUBJECT,
    OBSERVER_STATUS_BODY,
    OBSERVER_STATUS_KEY,
    OBSERVER_STATUS_SUBJECT,
)
from app.settings import Settings

logger = logging.getLogger("app.notifications")


async def _title(session: AsyncSession, application_id: UUID) -> str:
    """Return the title of the application, or an empty string."""
    data = await session.scalar(select(Application.data).where(Application.id == application_id))
    title = data.get("title") if isinstance(data, dict) else None
    return title.strip() if isinstance(title, str) else ""


async def _has_account(session: AsyncSession, email: str) -> bool:
    """Tell whether an active account holds the address (case-insensitive)."""
    from app.modules.auth.models import Principal as PrincipalRow

    found = await session.scalar(
        select(PrincipalRow.id).where(PrincipalRow.email == email, PrincipalRow.active.is_(True))
    )
    return found is not None


async def notify_observer_added(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    application_id: UUID,
    observer_id: UUID,
) -> bool:
    """Send the mail to a new observer.

    The caller owns the session and commits it, because the login link is a row.

    Returns:
        True when the mail is enqueued; False when the observer is gone.
    """
    from app.modules.applications import email_login

    row = await session.get(ApplicationObserver, observer_id)
    if row is None:
        return False
    name = await session.scalar(
        select(Applicant.name).where(Applicant.application_id == application_id)
    )
    lang = await resolve_application_lang(session, application_id=application_id, settings=settings)
    link = await email_login.issue_confirm_link(session, settings, email=row.email)
    service = NotificationService(session, queue=queue, settings=settings)
    return await service.send_kind_mail(
        [row.email],
        kind=OBSERVER_ADDED_KEY,
        template_key=OBSERVER_ADDED_KEY,
        builtin_subject=OBSERVER_ADDED_SUBJECT,
        builtin_body=OBSERVER_ADDED_BODY,
        context={
            "applicationTitle": await _title(session, application_id),
            "applicantName": name or "",
            "endLink": end_link(settings.public_base_url, settings.magic_link_secret, observer_id),
            "applicationId": str(application_id),
        },
        idempotency_parts=(OBSERVER_ADDED_KEY, str(observer_id)),
        lang=lang,
        link=MailLink(link, "application"),
    )


async def send_observer_status_mails(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    application_id: UUID,
    context: dict[str, Any],
    idempotency_base: str,
) -> int:
    """Send the status mail of an application to each of its observers.

    ``context`` is the context of the applicant mail (title, status, amounts). The
    language is the language of the application.

    Returns:
        The number of enqueued mails.
    """
    observers = await list_observers(session, application_id)
    if not observers:
        return 0
    lang = await resolve_application_lang(session, application_id=application_id, settings=settings)
    service = NotificationService(session, queue=queue, settings=settings)
    sent = [
        await service.send_kind_mail(
            [row.email],
            kind="status_update",
            template_key=OBSERVER_STATUS_KEY,
            builtin_subject=OBSERVER_STATUS_SUBJECT,
            builtin_body=OBSERVER_STATUS_BODY,
            context={
                **context,
                "endLink": end_link(settings.public_base_url, settings.magic_link_secret, row.id),
                "applicationId": str(application_id),
            },
            idempotency_parts=(idempotency_base, OBSERVER_STATUS_KEY, str(row.id)),
            lang=lang,
            link=application_link(
                settings, application_id, guest=not await _has_account(session, row.email)
            ),
        )
        for row in observers
    ]
    return sum(sent)

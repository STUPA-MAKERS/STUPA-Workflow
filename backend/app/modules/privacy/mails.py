"""Erasure-request mails to the data subject: executed, rejected.

Each function runs as a background task after the triggering transaction
commits. Each opens its own sessionmaker. The send is best effort. The builtin
subject and body dicts are also the editor defaults.

The rejection links the application of the request. The mail about an executed
request has no link, because the erasure removed the element: the application is
anonymized and its page shows nothing to the data subject. The mail to the admins
about a new request is in `app.modules.applications.erasure_mail`.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.db import get_sessionmaker
from app.modules.notifications.links import application_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.privacy import (
    ERASURE_EXECUTED_BODY,
    ERASURE_EXECUTED_SUBJECT,
    ERASURE_REJECTED_BODY,
    ERASURE_REJECTED_SUBJECT,
)
from app.settings import Settings

logger = logging.getLogger("app.privacy")


async def notify_erasure_executed(
    *,
    queue: MailQueue | None,
    settings: Settings,
    request_id: UUID,
    email: str | None,
    subject_type: str,
) -> None:
    """Notify the data subject that the request was executed.

    The function sends nothing when the email is unknown.
    """
    if not email:
        return
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await NotificationService(session, queue=queue, settings=settings).send_kind_mail(
            [email],
            kind="privacy",
            template_key="erasure_executed",
            builtin_subject=ERASURE_EXECUTED_SUBJECT,
            builtin_body=ERASURE_EXECUTED_BODY,
            context={"subjectType": subject_type, "requestId": str(request_id)},
            idempotency_parts=("erasure_executed", str(request_id)),
        )


async def notify_erasure_rejected(
    *,
    queue: MailQueue | None,
    settings: Settings,
    request_id: UUID,
    email: str | None,
    reason: str | None,
) -> None:
    """Notify the data subject that the request was rejected, with the reason.

    The function sends nothing when the email is unknown.

    The rejected request leaves the application as it is, so the mail links to it; a guest
    (no account) gets the public applicant page.
    """
    if not email:
        return
    from app.modules.applications.models import Application
    from app.modules.privacy.models import ErasureRequest

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(ErasureRequest.application_id, Application.created_by)
                .outerjoin(Application, Application.id == ErasureRequest.application_id)
                .where(ErasureRequest.id == request_id)
            )
        ).first()
        app_id, created_by = row if row is not None else (None, None)
        link = (
            application_link(settings, app_id, guest=created_by is None)
            if app_id is not None
            else None
        )
        await NotificationService(session, queue=queue, settings=settings).send_kind_mail(
            [email],
            kind="privacy",
            template_key="erasure_rejected",
            builtin_subject=ERASURE_REJECTED_SUBJECT,
            builtin_body=ERASURE_REJECTED_BODY,
            context={"reason": reason or "", "requestId": str(request_id)},
            idempotency_parts=("erasure_rejected", str(request_id)),
            link=link,
        )

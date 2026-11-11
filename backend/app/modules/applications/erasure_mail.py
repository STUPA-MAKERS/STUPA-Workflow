"""Mail to the privacy admins about a new erasure request.

The function runs as a background task after the triggering transaction commits. It
opens its own sessionmaker. The send is best effort. The mail links the privacy admin
page. The file is in `applications`, because an applicant starts the request on the
page of the application, and `applications` must not import `privacy`.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.db import get_sessionmaker
from app.modules.notifications.links import privacy_admin_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import RecipientResolver
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.privacy import (
    ERASURE_REQUESTED_BODY,
    ERASURE_REQUESTED_SUBJECT,
)
from app.settings import Settings

logger = logging.getLogger("app.privacy")


async def notify_erasure_requested(
    *,
    queue: MailQueue | None,
    settings: Settings,
    request_id: UUID,
    subject_type: str,
) -> None:
    """Notify the privacy admins (`privacy.manage`) about a new request."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        recipients = await RecipientResolver(session).resolve(
            [{"kind": "permission", "ref": "privacy.manage"}]
        )
        if not recipients:
            return
        await NotificationService(session, queue=queue, settings=settings).send_kind_mail(
            recipients,
            kind="privacy",
            template_key="erasure_requested",
            builtin_subject=ERASURE_REQUESTED_SUBJECT,
            builtin_body=ERASURE_REQUESTED_BODY,
            context={"subjectType": subject_type, "requestId": str(request_id)},
            idempotency_parts=("erasure_requested", str(request_id)),
            link=privacy_admin_link(settings),
        )

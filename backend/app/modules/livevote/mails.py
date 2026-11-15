"""Mail for a new meeting.

The entry point runs as a background task with its own session after the API
response. It is best effort. A mail failure must never break the request that
triggered it. The code logs the exception and drops it.

Sending goes through `NotificationService.send_kind_mail`. That call applies
the preference filter, the layout and the DB template with a builtin fallback.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.db import get_sessionmaker
from app.modules.notifications.links import meeting_link
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.meetings import (
    BUILTIN_ABSENCE_LIMIT_BODY,
    BUILTIN_ABSENCE_LIMIT_SUBJECT,
    BUILTIN_MEETING_BODY,
    BUILTIN_MEETING_SUBJECT,
)
from app.settings import Settings

logger = logging.getLogger("app.notifications")


class MeetingMailer:
    """Background entry point of the meeting mail: best effort, own session."""

    async def meeting_created(
        self, settings: Settings, meeting_id: uuid.UUID, pool: object
    ) -> None:
        """Mail a new meeting to the members of its Gremium; log a failure."""
        try:
            await self._meeting_created(settings, meeting_id, pool)
        except Exception:
            logger.exception("meeting mail failed (meeting=%s)", meeting_id)

    async def _meeting_created(
        self, settings: Settings, meeting_id: uuid.UUID, pool: object
    ) -> None:
        from app.modules.gremien.models import Gremium
        from app.modules.meetings.models import Meeting
        from app.modules.notifications.recipients import RecipientResolver

        queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            meeting = await session.get(Meeting, meeting_id)
            if meeting is None:
                return
            gremium_name = await session.scalar(
                select(Gremium.name).where(Gremium.id == meeting.gremium_id)
            )
            recipients = await RecipientResolver(session).resolve(
                [{"kind": "gremium", "ref": str(meeting.gremium_id)}]
            )
            service = NotificationService(session, queue=queue, settings=settings)
            await service.send_kind_mail(
                recipients,
                kind="meeting",
                template_key="meeting_created",
                builtin_subject=BUILTIN_MEETING_SUBJECT,
                builtin_body=BUILTIN_MEETING_BODY,
                context={
                    "meetingId": str(meeting.id),
                    "meetingTitle": meeting.title,
                    "meetingDate": meeting.date.strftime("%d.%m.%Y") if meeting.date else "",
                    "meetingTime": meeting.start_time.strftime("%H:%M")
                    if meeting.start_time
                    else "",
                    "gremiumName": gremium_name or "",
                },
                idempotency_parts=("meeting_created", str(meeting.id)),
                link=meeting_link(settings, meeting.id),
            )

    async def absence_limit(self, settings: Settings, meeting_id: uuid.UUID, pool: object) -> None:
        """Mail the absence notices of a closed meeting to its managers; log a failure."""
        try:
            await self._absence_limit(settings, meeting_id, pool)
        except Exception:
            logger.exception("absence mail failed (meeting=%s)", meeting_id)

    async def _absence_limit(self, settings: Settings, meeting_id: uuid.UUID, pool: object) -> None:
        from app.modules.gremien.models import Gremium
        from app.modules.livevote.open_window import load_meeting_settings
        from app.modules.meetings.absence import absence_notices, manager_emails
        from app.modules.meetings.models import Meeting

        queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            meeting = await session.get(Meeting, meeting_id)
            if meeting is None:
                return
            notices = await absence_notices(session, meeting, await load_meeting_settings(session))
            recipients = await manager_emails(session, meeting.gremium_id) if notices else []
            if not recipients:
                return
            gremium_name = await session.scalar(
                select(Gremium.name).where(Gremium.id == meeting.gremium_id)
            )
            service = NotificationService(session, queue=queue, settings=settings)
            for notice in notices:
                await service.send_kind_mail(
                    recipients,
                    kind="meeting",
                    template_key="absence_limit",
                    builtin_subject=BUILTIN_ABSENCE_LIMIT_SUBJECT,
                    builtin_body=BUILTIN_ABSENCE_LIMIT_BODY,
                    context={
                        "meetingId": str(meeting.id),
                        "meetingTitle": meeting.title,
                        "meetingDate": meeting.date.strftime("%d.%m.%Y") if meeting.date else "",
                        "gremiumName": gremium_name or "",
                        "memberName": notice.name,
                        "count": notice.count,
                        "limit": notice.limit,
                        "reached": notice.reached,
                    },
                    idempotency_parts=(
                        "absence_limit",
                        str(meeting.id),
                        str(notice.principal_id),
                    ),
                    link=meeting_link(settings, meeting.id),
                )


def get_meeting_mailer() -> MeetingMailer:
    """Return the meeting mailer (tests can override this dependency)."""
    return MeetingMailer()

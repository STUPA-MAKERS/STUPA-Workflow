"""Mails for a granted or revoked meeting delegation.

The entry point runs as a background task with its own session after the API
response. It is best effort. A mail failure must never break the request that
triggered it. The code logs the exception and drops it.

Sending goes through `NotificationService.send_kind_mail`. That call applies
the preference filter, the layout and the DB template with a builtin fallback.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.db import get_sessionmaker
from app.modules.notifications.links import meeting_link
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.meetings import (
    BUILTIN_DELEGATION_GRANTED_BODY,
    BUILTIN_DELEGATION_GRANTED_SUBJECT,
    BUILTIN_DELEGATION_REVOKED_BODY,
    BUILTIN_DELEGATION_REVOKED_SUBJECT,
)
from app.settings import Settings

logger = logging.getLogger("app.notifications")


@dataclass(frozen=True, slots=True)
class DelegationMailInfo:
    """Delegation data collected before the send or before the revocation.

    The source is the session-bound `meeting_delegation` row.
    """

    delegation_id: uuid.UUID
    email: str | None
    meeting_title: str
    meeting_date: str | None
    gremium_name: str | None
    delegator_name: str | None
    voting: bool
    meeting_id: uuid.UUID | None = None


async def meeting_delegation_mail_info(
    session: object, delegation_id: uuid.UUID, *, to_delegator: bool = False
) -> DelegationMailInfo | None:
    """Collect the mail data of a meeting delegation (best effort).

    The mail goes to the delegate. ``to_delegator`` sends it to the delegator
    instead: the access revoke takes the rights of a delegate, and the delegator
    then loses the representation.
    """
    from app.modules.auth.models import Principal
    from app.modules.delegations.models import MeetingDelegation
    from app.modules.gremien.models import Gremium
    from app.modules.livevote.models import Meeting

    delegator = Principal.__table__.alias("delegator")
    try:
        row = (
            await session.execute(  # type: ignore[attr-defined]
                select(
                    Principal.email,
                    Meeting.title,
                    Meeting.date,
                    Gremium.name,
                    delegator.c.display_name,
                    delegator.c.email,
                    MeetingDelegation.delegate_voting,
                    Meeting.id,
                )
                .join(
                    Principal,
                    Principal.id
                    == (
                        MeetingDelegation.delegator_principal_id
                        if to_delegator
                        else MeetingDelegation.delegate_principal_id
                    ),
                )
                .join(Meeting, Meeting.id == MeetingDelegation.meeting_id)
                .outerjoin(Gremium, Gremium.id == MeetingDelegation.gremium_id)
                .outerjoin(
                    delegator,
                    delegator.c.id == MeetingDelegation.delegator_principal_id,
                )
                .where(MeetingDelegation.id == delegation_id)
            )
        ).first()
    except Exception:
        logger.exception("delegation mail info failed (delegation=%s)", delegation_id)
        return None
    if row is None:
        return None
    email, title, date, gremium_name, d_name, d_email, voting, meeting_id = row
    return DelegationMailInfo(
        delegation_id=delegation_id,
        email=email,
        meeting_title=title,
        meeting_date=date.strftime("%d.%m.%Y") if date else None,
        gremium_name=gremium_name,
        delegator_name=d_name or d_email,
        voting=bool(voting),
        meeting_id=meeting_id,
    )


class DelegationMailer:
    """Background entry point of the delegation mails: best effort, own session."""

    async def delegation_changed(
        self,
        settings: Settings,
        info: DelegationMailInfo | None,
        *,
        granted: bool,
        pool: object,
    ) -> None:
        """Mail a granted or revoked delegation; log a failure."""
        try:
            await self._delegation_changed(settings, info, granted=granted, pool=pool)
        except Exception:
            logger.exception("delegation mail failed")

    async def _delegation_changed(
        self,
        settings: Settings,
        info: DelegationMailInfo | None,
        *,
        granted: bool,
        pool: object,
    ) -> None:
        if info is None or not info.email:
            return
        template_key = "delegation_granted" if granted else "delegation_revoked"
        builtin = (
            (BUILTIN_DELEGATION_GRANTED_SUBJECT, BUILTIN_DELEGATION_GRANTED_BODY)
            if granted
            else (
                BUILTIN_DELEGATION_REVOKED_SUBJECT,
                BUILTIN_DELEGATION_REVOKED_BODY,
            )
        )
        queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = NotificationService(session, queue=queue, settings=settings)
            await service.send_kind_mail(
                [info.email],
                kind="delegation",
                template_key=template_key,
                builtin_subject=builtin[0],
                builtin_body=builtin[1],
                context={
                    "meetingTitle": info.meeting_title,
                    "meetingDate": info.meeting_date or "",
                    "gremiumName": info.gremium_name or "",
                    "delegatorName": info.delegator_name or "",
                    "voting": info.voting,
                },
                idempotency_parts=(
                    template_key,
                    str(info.delegation_id),
                ),
                link=meeting_link(settings, info.meeting_id)
                if info.meeting_id is not None
                else None,
            )


def get_delegation_mailer() -> DelegationMailer:
    """Return the delegation mailer (tests can override this dependency)."""
    return DelegationMailer()

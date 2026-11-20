"""The message of a Gremium to its members (specs 001850-001854).

The send needs the gremium permission ``members.notify`` from the own gremium role,
without the admin bypass, because a gremium right comes only from the membership. The
message goes to each member of the Gremium and to each person in its substitute pool,
with an active account and an address, the sender included. A former member has no
membership row, so it gets none. A person who is member and pool substitute gets one
mail.

Each recipient gets an own mail, so no member sees the addresses of the others. The
Reply-To is the address of the sender, so the answers go to the sender. The template
``gremium_message`` is in no notification kind, so a member cannot switch it off. Each
send writes one ``gremium_notify`` audit entry with the subject and the number of
recipients, never an address or the text.
"""

from __future__ import annotations

import uuid
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.policy import holds_gremium_permission
from app.modules.auth.principal import Principal
from app.modules.gremien.models import DelegationSubstitute, Gremium, GremiumMembership
from app.modules.gremien_overview.schemas import GremiumNotifyIn, GremiumNotifyOut
from app.modules.notifications.links import committee_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.committees import (
    GREMIUM_MESSAGE_BODY,
    GREMIUM_MESSAGE_KEY,
    GREMIUM_MESSAGE_SUBJECT,
)
from app.settings import Settings
from app.shared.errors import ForbiddenError

MEMBERS_NOTIFY: Final = "members.notify"


async def member_addresses(db: AsyncSession, gremium_id: UUID) -> list[tuple[str, str]]:
    """Return ``(sub, email)`` of the members and the pool substitutes, sorted by sub.

    Only an active account with an address counts. A person in both sets counts once.
    """
    members = select(GremiumMembership.principal_id).where(
        GremiumMembership.gremium_id == gremium_id
    )
    pool = select(DelegationSubstitute.substitute_principal_id).where(
        DelegationSubstitute.gremium_id == gremium_id
    )
    rows = (
        await db.execute(
            select(PrincipalRow.sub, PrincipalRow.email).where(
                PrincipalRow.id.in_(members.union(pool)),
                PrincipalRow.active.is_(True),
                PrincipalRow.email.is_not(None),
            )
        )
    ).all()
    return sorted({str(sub): str(email) for sub, email in rows if email}.items())


async def notify_members(
    db: AsyncSession,
    principal: Principal,
    gremium_id: UUID,
    body: GremiumNotifyIn,
    *,
    queue: MailQueue | None,
    settings: Settings,
) -> GremiumNotifyOut:
    """Send the message to every member and write the audit entry, without a commit.

    Raises:
        ForbiddenError: The caller does not hold ``members.notify`` in the Gremium (403).
    """
    if not await holds_gremium_permission(db, principal, MEMBERS_NOTIFY, gremium_id):
        raise ForbiddenError("not allowed to notify the members of this gremium")
    sender = (
        await db.execute(
            select(PrincipalRow.display_name, PrincipalRow.email).where(
                PrincipalRow.sub == principal.sub
            )
        )
    ).one_or_none()
    sender_name = (sender.display_name if sender else None) or principal.display_name or ""
    reply_to = sender.email if sender else None
    gremium_name = await db.scalar(select(Gremium.name).where(Gremium.id == gremium_id)) or ""
    members = await member_addresses(db, gremium_id)
    service = NotificationService(db, queue=queue, settings=settings)
    send_id = uuid.uuid4().hex
    context: dict[str, object] = {
        "gremiumName": gremium_name,
        "senderName": sender_name,
        "subject": body.subject,
        "message": body.message,
    }
    for sub, email in members:
        await service.send_kind_mail(
            [email],
            kind=GREMIUM_MESSAGE_KEY,
            template_key=GREMIUM_MESSAGE_KEY,
            builtin_subject=GREMIUM_MESSAGE_SUBJECT,
            builtin_body=GREMIUM_MESSAGE_BODY,
            context=context,
            idempotency_parts=(GREMIUM_MESSAGE_KEY, send_id, sub),
            link=committee_link(settings, gremium_id),
            reply_to=reply_to,
        )
    await audit_record(
        db,
        actor=principal.sub,
        action=AuditAction.GREMIUM_NOTIFY,
        target_type="gremium",
        target_id=str(gremium_id),
        data={
            "gremiumId": str(gremium_id),
            "subject": body.subject,
            "recipients": len(members),
        },
    )
    return GremiumNotifyOut(recipients=len(members))

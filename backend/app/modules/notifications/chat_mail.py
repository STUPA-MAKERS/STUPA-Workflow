"""Helpers that the mails about a chat message share.

The comment mails, the mention mails and the ticket mails build their text and their
recipient list with these functions. A mentioned person is a member, so the mail names
the actor with the display name. Only an active account with an address gets a mail.
Each recipient gets an own mail with the idempotency key (key, message id, recipient).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications.links import MailLink
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.mentions import (
    MENTION_KIND,
)
from app.settings import Settings

logger = logging.getLogger("app.notifications")


def maker(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
) -> async_sessionmaker[AsyncSession]:
    """Return the given sessionmaker, or the one of the app without one."""
    return sessionmaker if sessionmaker is not None else get_sessionmaker()


def display_name(row: PrincipalRow | None) -> str:
    """Return the display name of the account, else its address, else an empty text."""
    if row is None:
        return ""
    return row.display_name or row.email or ""


async def addresses(
    session: AsyncSession, ids: Sequence[UUID], *, skip: UUID | None
) -> list[tuple[UUID, str]]:
    """Return ``(id, e-mail)`` of the active accounts with an address, without ``skip``."""
    wanted = [pid for pid in dict.fromkeys(ids) if pid != skip]
    if not wanted:
        return []
    rows = (
        await session.execute(
            select(PrincipalRow.id, PrincipalRow.email).where(
                PrincipalRow.id.in_(wanted),
                PrincipalRow.active.is_(True),
                PrincipalRow.merged_into.is_(None),
                PrincipalRow.email.is_not(None),
            )
        )
    ).all()
    found = {pid: str(email) for pid, email in rows if email}
    return [(pid, found[pid]) for pid in wanted if pid in found]


async def send_each(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    recipients: list[tuple[UUID, str]],
    key: str,
    subject: dict[str, str],
    body: dict[str, str],
    html: dict[str, str],
    context: dict[str, object],
    message_id: UUID,
    link: MailLink,
) -> int:
    """Send one mail of the kind ``mention`` to each recipient and return the count."""
    service = NotificationService(session, queue=queue, settings=settings)

    async def send_to(pid: UUID, address: str) -> bool:
        return await service.send_kind_mail(
            [address],
            kind=MENTION_KIND,
            template_key=key,
            builtin_subject=subject,
            builtin_body=body,
            builtin_html=html,
            context=context,
            idempotency_parts=(key, str(message_id), str(pid)),
            link=link,
        )

    sent = [await send_to(pid, address) for pid, address in recipients]
    return sum(sent)


def comment_mail_text(body: str, filenames: list[str]) -> str:
    """Return the text of a comment mail: the body, or the file names without one."""
    if body.strip() or not filenames:
        return body
    return ", ".join(filenames)


def initials(name: str) -> str:
    """Return the initials for the mail avatar (same rule as the web-UI chat)."""
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    first = parts[0][0]
    last = parts[-1][0] if len(parts) > 1 else ""
    return (first + last).upper()

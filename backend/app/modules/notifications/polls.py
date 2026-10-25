"""Poll mails: ``poll_started`` and ``poll_reminder``.

Only a poll of a Gremium (no meeting) sends mail. A meeting poll runs in the room.

* ``poll_started`` goes to every eligible member (an active member with the gremium
  permission ``vote.cast``) when the poll opens. The router sends it after the commit
  as a background task with its own session (best effort: a mail failure never fails
  the open).
* ``poll_reminder`` goes once, 24 h before the end, to the eligible members without
  an answer. The deadline cron sends it (``worker/polls.py``) and stores
  ``vote.reminded_at``. A poll that runs less than 24 h gets no reminder.

Each kind is in ``NOTIFICATION_KINDS``, so a member can switch it off. The link opens
the poll on the page "Abstimmungen". A secret poll keeps the identity apart from the
choice, but its ``voted_marker`` still tells who answered, so the reminder works for
both.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.admin.gremium_roles import _time_valid_clause
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications.links import vote_link
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.voting.models import Ballot, Vote, VotedMarker
from app.settings import Settings

logger = logging.getLogger("app.notifications")

POLL_STARTED_KEY = "poll_started"
POLL_REMINDER_KEY = "poll_reminder"

POLL_STARTED_SUBJECT: dict[str, str] = {
    "de": "Neue Umfrage: {{ question }}",
    "en": "New poll: {{ question }}",
}
POLL_STARTED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nim Gremium {{ gremiumName }} läuft eine Umfrage:\n\n{{ question }}\n\n"
    "Sie endet am {{ closesAt }}.\n",
    "en": "Hello,\n\nthe committee {{ gremiumName }} runs a poll:\n\n{{ question }}\n\n"
    "It ends on {{ closesAt }}.\n",
}
POLL_REMINDER_SUBJECT: dict[str, str] = {
    "de": "Erinnerung: Umfrage „{{ question }}“",
    "en": 'Reminder: poll "{{ question }}"',
}
POLL_REMINDER_BODY: dict[str, str] = {
    "de": "Hallo,\n\ndie Umfrage „{{ question }}“ im Gremium {{ gremiumName }} endet am "
    "{{ closesAt }}. Sie haben noch nicht geantwortet.\n",
    "en": 'Hello,\n\nthe poll "{{ question }}" of the committee {{ gremiumName }} ends on '
    "{{ closesAt }}. You have not answered yet.\n",
}
POLL_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zur Umfrage (ohne den Platzhalter hängt die Mail ihn an)",
    "question": "Frage der Umfrage",
    "gremiumName": "Name des Gremiums",
    "closesAt": "Ende der Umfrage (TT.MM.JJJJ, HH:MM)",
}


def _maker(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
) -> async_sessionmaker[AsyncSession]:
    return sessionmaker if sessionmaker is not None else get_sessionmaker()


def _end_text(closes_at: datetime | None, settings: Settings) -> str:
    """Return the end of a poll in the local time zone (``30.10.2026, 12:00``)."""
    if closes_at is None:
        return ""
    local = closes_at.astimezone(ZoneInfo(settings.local_timezone))
    return local.strftime("%d.%m.%Y, %H:%M")


async def eligible_members(
    session: AsyncSession, gremium_id: UUID, now: datetime
) -> list[tuple[str, str]]:
    """Return ``(sub, email)`` of the active members with ``vote.cast`` in the Gremium.

    The rule is the roster of a vote (``MeetingService.vote_eligible_count``): a
    membership valid now with a gremium role that holds ``vote.cast``. A deactivated
    account and an account without an address get no mail.
    """
    rows = (
        await session.execute(
            select(PrincipalRow.sub, PrincipalRow.email, GremiumRole.permissions)
            .join(GremiumMembership, GremiumMembership.principal_id == PrincipalRow.id)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .where(
                GremiumMembership.gremium_id == gremium_id,
                _time_valid_clause(now),
                PrincipalRow.active.is_(True),
                PrincipalRow.email.is_not(None),
            )
        )
    ).all()
    found: dict[str, str] = {}
    for sub, email, perms in rows:
        if "vote.cast" in (perms or []) and email:
            found[str(sub)] = str(email)
    return sorted(found.items())


async def _answered(session: AsyncSession, vote_id: UUID) -> set[str]:
    """Return the voter keys with an answer: the open ballots and the secret markers."""
    subs: set[str] = set()
    for model in (Ballot, VotedMarker):
        subs.update(
            str(sub)
            for sub in (
                await session.scalars(select(model.voter_sub).where(model.vote_id == vote_id))
            ).all()
        )
    return subs


async def send_poll_mail(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    vote: Vote,
    now: datetime,
    reminder: bool,
) -> bool:
    """Send ``poll_started`` (every eligible member) or ``poll_reminder`` (no answer yet).

    Each member gets an own mail with an own idempotency key (kind, vote, member),
    because a shared To: line would show every member who has not answered yet, which
    a secret poll must not reveal.

    Returns:
        True when at least one mail was enqueued.
    """
    if vote.meeting_id is not None or vote.kind != "poll":
        return False
    gremium_id = UUID(vote.eligible_group)
    members = await eligible_members(session, gremium_id, now)
    if reminder:
        answered = await _answered(session, vote.id)
        members = [(sub, email) for sub, email in members if sub not in answered]
    if not members:
        return False
    gremium_name = await session.scalar(select(Gremium.name).where(Gremium.id == gremium_id))
    key = POLL_REMINDER_KEY if reminder else POLL_STARTED_KEY
    context: dict[str, object] = {
        "question": vote.question or "",
        "gremiumName": gremium_name or "",
        "closesAt": _end_text(vote.closes_at, settings),
    }
    service = NotificationService(session, queue=queue, settings=settings)
    sent = False
    for sub, email in members:
        if await service.send_kind_mail(
            [email],
            kind=key,
            template_key=key,
            builtin_subject=POLL_REMINDER_SUBJECT if reminder else POLL_STARTED_SUBJECT,
            builtin_body=POLL_REMINDER_BODY if reminder else POLL_STARTED_BODY,
            context=context,
            idempotency_parts=(key, str(vote.id), sub),
            link=vote_link(settings, vote.id),
        ):
            sent = True
    return sent


async def notify_poll_started(
    settings: Settings,
    vote_id: UUID,
    pool: object,
    *,
    now: datetime,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """Send ``poll_started`` after the open of a poll of a Gremium (best effort).

    Returns:
        True when a mail was enqueued.
    """
    try:
        queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
        async with _maker(sessionmaker)() as session:
            vote = await session.get(Vote, vote_id)
            if vote is None or vote.status != "open":
                return False
            return await send_poll_mail(
                session, queue=queue, settings=settings, vote=vote, now=now, reminder=False
            )
    except Exception:
        logger.exception("poll_started mail failed (vote=%s)", vote_id)
        return False

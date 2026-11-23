"""arq cron task: fetch the mails of each Postfach that is on.

``fetch_ticket_mails`` runs every minute (§F/integrations/ticket-mail/002723). It opens
no connection for a Postfach whose switch is off (§F/integrations/ticket-mail/002722),
and it checks the host against ``TICKET_MAIL_HOST_ALLOWLIST`` again before each
connection (§NF/security/network/002744), because the list can change after the save.

Each mail has its own transaction. The job moves a mail to the folder for done mails
after the commit of its ticket, and it stores the position in the inbox after that. A
failure in the middle leaves the mail in the inbox, and the next run takes it again; the
identity of the mail then stops a second ticket (§F/integrations/ticket-mail/002724).

A mail above the rate limit of its address stays in the inbox, and the position stops
before it, so a later run takes it (§F/integrations/ticket-mail/002741).

A failure of one Postfach counts on that Postfach and does not stop the others. The run
that fails stores the short cause code. The admin page shows it after eight failed runs
in sequence. A run without a failure clears the count.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.files.queue import ScanQueue, scan_queue_from_pool
from app.modules.files.service import FilesService
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.tickets.mail_client import MailAccount, MailError
from app.modules.tickets.mail_import import MailImporter, Taken
from app.modules.tickets.mail_inbox import MAX_SOURCE_BYTES, Inbox, open_inbox
from app.modules.tickets.mail_parse import parse_mail
from app.modules.tickets.mailbox import host_allowed, imap_account
from app.modules.tickets.mails import notify_ticket_created, notify_ticket_note
from app.modules.tickets.models import TicketMailbox
from app.settings import Settings

logger = logging.getLogger("worker.ticket_mail")

#: The mails that one run reads from one inbox.
BATCH = 50
#: The cause code of a failure that is no failure of the mail server.
IMPORT_FAILED = "import_failed"
#: The cause code of a host outside the allowlist.
HOST_NOT_ALLOWED = "mail_host_not_allowed"

#: One step of a run: the UID of a mail and what became of it.
_Step = tuple[int, Taken]


@dataclass(frozen=True, slots=True)
class _Box:
    """The values of a Postfach that one run needs."""

    id: UUID
    account: MailAccount
    done_folder: str
    uid_validity: int | None
    last_uid: int


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via ``ctx['ticket_mail_sessionmaker']``)."""
    maker = ctx.get("ticket_mail_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    queue: MailQueue | None = ctx.get("mail_queue")
    if queue is not None:
        return queue
    pool = ctx.get("redis")
    return ArqMailQueue(pool) if pool is not None else None


def _scan_queue(ctx: dict[str, Any]) -> ScanQueue | None:
    queue: ScanQueue | None = ctx.get("scan_queue")
    return queue if queue is not None else scan_queue_from_pool(ctx.get("redis"))


async def _open(ctx: dict[str, Any], account: MailAccount) -> Inbox:
    """Open the inbox in a thread (tests inject ``ctx['ticket_mail_inbox']``)."""
    opener = ctx.get("ticket_mail_inbox") or open_inbox
    return await asyncio.to_thread(opener, account)


async def _boxes(maker: async_sessionmaker[AsyncSession]) -> list[_Box]:
    async with maker() as session:
        rows = (
            await session.scalars(
                select(TicketMailbox)
                .where(TicketMailbox.enabled.is_(True))
                .order_by(TicketMailbox.created_at, TicketMailbox.id)
            )
        ).all()
        return [
            _Box(
                id=row.id,
                account=imap_account(row),
                done_folder=row.done_folder,
                uid_validity=row.uid_validity,
                last_uid=row.last_uid,
            )
            for row in rows
        ]


async def fetch_ticket_mails(ctx: dict[str, Any], now: datetime | None = None) -> int:
    """Fetch the new mails of each Postfach that is on.

    Returns:
        The number of mails that became a ticket or a message.
    """
    moment = now or datetime.now(UTC)
    maker = _sessionmaker(ctx)
    return sum([await _fetch_box(ctx, maker, box, moment) for box in await _boxes(maker)])


async def _fetch_box(
    ctx: dict[str, Any], maker: async_sessionmaker[AsyncSession], box: _Box, moment: datetime
) -> int:
    """Run one Postfach; a failure counts on it and does not reach the caller."""
    try:
        return await _run_box(ctx, maker, box, moment)
    except MailError as exc:
        await _count_failure(maker, box.id, exc.code)
    except Exception:
        logger.exception("ticket mail fetch crashed (mailbox=%s)", box.id)
        await _count_failure(maker, box.id, IMPORT_FAILED)
    return 0


async def _run_box(
    ctx: dict[str, Any], maker: async_sessionmaker[AsyncSession], box: _Box, moment: datetime
) -> int:
    settings: Settings = ctx["settings"]
    if not host_allowed(box.account.host, box.account.port, settings.ticket_mail_host_allowlist):
        raise MailError(HOST_NOT_ALLOWED)
    inbox = await _open(ctx, box.account)
    try:
        start = box.last_uid if inbox.uid_validity == box.uid_validity else 0
        uids = (await asyncio.to_thread(inbox.uids_after, start))[:BATCH]
        steps, failure = await _walk(ctx, maker, inbox, box, uids, ())
    finally:
        await asyncio.to_thread(inbox.close)
    await _save(maker, box.id, inbox.uid_validity, _position(start, steps), failure, moment)
    return sum(taken.kind in {"ticket", "message"} for _uid, taken in steps)


def _position(start: int, steps: tuple[_Step, ...]) -> int:
    """Return the highest UID that the next run does not read again.

    The position stops before the first mail above the rate limit, so that mail comes
    back. A mail after it that was imported is not in the inbox any more.
    """
    waiting = [uid for uid, taken in steps if taken.kind == "deferred"]
    if waiting:
        return min(waiting) - 1
    return max((uid for uid, _taken in steps), default=start)


async def _walk(
    ctx: dict[str, Any],
    maker: async_sessionmaker[AsyncSession],
    inbox: Inbox,
    box: _Box,
    uids: list[int],
    done: tuple[_Step, ...],
) -> tuple[tuple[_Step, ...], str | None]:
    """Take the mails in sequence; stop at the first failure and return its cause code."""
    if not uids:
        return done, None
    try:
        taken = await _take(ctx, maker, inbox, box, uids[0])
    except MailError as exc:
        return done, exc.code
    except Exception:
        logger.exception("ticket mail import failed (mailbox=%s)", box.id)
        return done, IMPORT_FAILED
    return await _walk(ctx, maker, inbox, box, uids[1:], (*done, (uids[0], taken)))


async def _take(
    ctx: dict[str, Any],
    maker: async_sessionmaker[AsyncSession],
    inbox: Inbox,
    box: _Box,
    uid: int,
) -> Taken:
    """Import one mail in its own transaction, then move it and tell the team."""
    if await asyncio.to_thread(inbox.size, uid) > MAX_SOURCE_BYTES:
        logger.warning("mail above the size limit stays in the inbox (mailbox=%s)", box.id)
        return Taken("ignored")
    source = await asyncio.to_thread(inbox.fetch, uid)
    settings: Settings = ctx["settings"]
    async with maker() as session:
        row = await session.get(TicketMailbox, box.id)
        if row is None:
            return Taken("ignored")
        files = FilesService(session, storage=ctx.get("object_storage"), settings=settings)
        importer = MailImporter(session, files, ctx.get("scanner"))
        taken = await importer.take(row, parse_mail(source), source)
        await session.commit()
    if taken.moves:
        await asyncio.to_thread(inbox.move, uid, box.done_folder)
    await _after(ctx, maker, taken)
    return taken


async def _after(
    ctx: dict[str, Any], maker: async_sessionmaker[AsyncSession], taken: Taken
) -> None:
    """Start the scans and the mails to the team; a failure here only logs."""
    settings: Settings = ctx["settings"]
    try:
        scans = _scan_queue(ctx)
        if scans is not None:
            await asyncio.gather(*(scans.enqueue(aid) for aid in taken.attachment_ids))
        if taken.kind == "ticket" and taken.ticket_id is not None:
            await notify_ticket_created(
                queue=_mail_queue(ctx),
                settings=settings,
                ticket_id=taken.ticket_id,
                sessionmaker=maker,
            )
        if taken.kind == "message" and taken.note_id is not None:
            await notify_ticket_note(
                queue=_mail_queue(ctx), settings=settings, note_id=taken.note_id, sessionmaker=maker
            )
    except Exception:
        logger.exception("follow-up of a ticket mail failed")


async def _save(
    maker: async_sessionmaker[AsyncSession],
    box_id: UUID,
    uid_validity: int,
    last_uid: int,
    failure: str | None,
    moment: datetime,
) -> None:
    """Store the position after the commits of the mails, and the result of the run."""
    result = (
        {"failures": TicketMailbox.failures + 1, "last_error": failure}
        if failure is not None
        else {"failures": 0, "last_error": None, "fetched_at": moment}
    )
    async with maker() as session:
        await session.execute(
            update(TicketMailbox)
            .where(TicketMailbox.id == box_id)
            .values(uid_validity=uid_validity, last_uid=last_uid, **result)
        )
        await session.commit()


async def _count_failure(maker: async_sessionmaker[AsyncSession], box_id: UUID, code: str) -> None:
    async with maker() as session:
        await session.execute(
            update(TicketMailbox)
            .where(TicketMailbox.id == box_id)
            .values(failures=TicketMailbox.failures + 1, last_error=code)
        )
        await session.commit()

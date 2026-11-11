"""Mention mail ``comment_mentioned``.

A person whom a chat message newly mentions gets one mail: ``comment_mentioned`` for a
comment on an application (`app.modules.applications.mention_mails`),
``ticket_mentioned`` for a note on a ticket (`app.modules.tickets.mention_mails`).
"Newly" means the mentions that the write added (all of them at the create, at an edit only the ids
that the stored list did not hold), so an edit never mails a person twice. The actor
(the person who wrote the mention) never gets the mail.

Both run as background tasks after the commit, each with its own session, and both
are best effort: a mail failure never fails the write. The kind is ``mention``, so
each person can switch the mails off.

Each recipient gets an own mail with the idempotency key (key, message id, recipient).
The key is the arq job id, so an edit that removes a mention and then adds it again
sends no second mail while the queue still holds the first job.

A mentioned person is a member (a reader of the internal comments, or a holder of
``ticket.manage``), so the mail names the actor and the author with their display
names, and an internal comment mails like a public one. Only an active account with
an address that the message still mentions gets the mail. The mail uses the default
language of the platform, like every mail to the team. The excerpt is the text of the
message (``comment_mail_text``: the file names without a text), cut at the length of
the comment mails. The HTML body shows it as the chat bubble of the comment mails.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.models import Application, Comment
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.service import FilesService
from app.modules.notifications.chat_mail import (
    addresses,
    comment_mail_text,
    display_name,
    initials,
    maker,
    send_each,
)
from app.modules.notifications.links import application_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.texts.comments import (
    APPLICANT_AUTHOR_FALLBACK,
    COMMENT_EXCERPT_LEN,
)
from app.modules.notifications.texts.mentions import (
    COMMENT_MENTIONED_BODY,
    COMMENT_MENTIONED_HTML,
    COMMENT_MENTIONED_KEY,
    COMMENT_MENTIONED_SUBJECT,
)
from app.settings import Settings
from app.shared.i18n import pick_lang
from app.shared.mentions import mention_ids

logger = logging.getLogger("app.notifications")


async def send_comment_mentions(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    comment_id: UUID,
    recipients: Sequence[UUID],
    actor_sub: str,
) -> int:
    """Mail the newly mentioned members of an application comment.

    Returns:
        The number of enqueued mails.
    """
    comment = await session.get(Comment, comment_id)
    if comment is None or not recipients:
        return 0
    still = set(mention_ids(comment.mentions))
    actor = await session.scalar(select(PrincipalRow).where(PrincipalRow.sub == actor_sub))
    targets = await addresses(
        session,
        [pid for pid in recipients if pid in still],
        skip=actor.id if actor is not None else None,
    )
    if not targets:
        return 0
    data = await session.scalar(
        select(Application.data).where(Application.id == comment.application_id)
    )
    title = (data or {}).get("title")
    files = await FilesService(session).message_attachments("comment", [comment.id])
    text = comment_mail_text(comment.body, [a.filename for a in files.get(comment.id, [])])
    by_member = comment.author_kind == "principal" and bool(comment.author)
    author_row = (
        await session.scalar(select(PrincipalRow).where(PrincipalRow.sub == comment.author))
        if by_member
        else None
    )
    named = (
        display_name(author_row)
        if by_member
        else pick_lang(APPLICANT_AUTHOR_FALLBACK, settings.mail_default_lang)
    )
    author = named or display_name(actor)
    context: dict[str, object] = {
        "actor": display_name(actor),
        "applicationId": str(comment.application_id),
        "applicationTitle": title.strip() if isinstance(title, str) else "",
        "comment": text[:COMMENT_EXCERPT_LEN],
        "commentAuthor": author,
        "commentAuthorInitials": initials(author),
    }
    return await send_each(
        session,
        queue=queue,
        settings=settings,
        recipients=targets,
        key=COMMENT_MENTIONED_KEY,
        subject=COMMENT_MENTIONED_SUBJECT,
        body=COMMENT_MENTIONED_BODY,
        html=COMMENT_MENTIONED_HTML,
        context=context,
        message_id=comment.id,
        link=application_link(settings, comment.application_id, guest=False, comment_id=comment.id),
    )


async def notify_comment_mentions(
    *,
    queue: MailQueue | None,
    settings: Settings,
    comment_id: UUID,
    recipients: Sequence[UUID],
    actor_sub: str,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Run `send_comment_mentions` in an own session (best effort).

    Returns:
        The number of enqueued mails, 0 after a failure.
    """
    try:
        async with maker(sessionmaker)() as session:
            return await send_comment_mentions(
                session,
                queue=queue,
                settings=settings,
                comment_id=comment_id,
                recipients=recipients,
                actor_sub=actor_sub,
            )
    except Exception:
        logger.exception("comment_mentioned mail failed")
        return 0

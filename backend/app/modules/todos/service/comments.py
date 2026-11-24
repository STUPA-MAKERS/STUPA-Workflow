"""The comments of a card, with mentions and files."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.modules.auth.people import person_refs
from app.modules.auth.principal import Principal
from app.modules.files.drafts import bind_drafts, check_message_drafts
from app.modules.todos.models import TodoBoard, TodoCard, TodoComment
from app.modules.todos.schemas import TodoCommentOut
from app.modules.todos.service.common import _excerpt, _invalid, _now, _uuid_of
from app.modules.todos.service.details import DetailOps
from app.modules.todos.service.rows import _comment_out, _comment_people
from app.shared.errors import ForbiddenError, NotFoundError


class CommentOps(DetailOps):
    """Comment writes on a card."""

    async def _check_mentions(self, board: TodoBoard, mentions: Sequence[uuid.UUID]) -> None:
        if mentions and not set(mentions) <= await self.access.member_ids(board):
            raise _invalid(
                "Mentions must be members of the board.", "mention_not_member", "mentions"
            )

    async def add_comment(
        self,
        card_id: uuid.UUID,
        body: str,
        mentions: Sequence[uuid.UUID],
        principal: Principal,
        *,
        attachment_ids: Sequence[uuid.UUID] = (),
        draft_token: str | None = None,
        pepper: str = "",
    ) -> TodoCommentOut:
        """Add a comment and bind its files; new mentions get the mail ``todo_mentioned``.

        The method locks the board and then the card before the insert, because the
        insert takes a key-share lock on the card and the commit updates the board. In
        the other order it deadlocks with the Gremium delete and the erasure, which
        lock the board and then the cards ``FOR UPDATE``.

        Raises:
            NotFoundError: The card is not readable (HTTP 404).
            ValidationProblem: A mention outside the board, files without a draft
                token, or a draft that is missing, expired, foreign or infected
                (HTTP 422).
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        wanted = list(dict.fromkeys(mentions))
        await self._check_mentions(board, wanted)
        token = await check_message_drafts(
            self.session, attachment_ids=attachment_ids, token=draft_token, pepper=pepper
        )
        comment = TodoComment(
            id=uuid.uuid4(),
            card_id=card.id,
            author_id=actor,
            body=body,
            mentions=[str(m) for m in wanted],
            created_at=_now(),
        )
        self.session.add(comment)
        if token is not None:
            await self.session.flush()
            await bind_drafts(
                self.session,
                attachment_ids=attachment_ids,
                token=token,
                pepper=pepper,
                todo_comment_id=comment.id,
            )
        self._touch(board, card)
        await self.session.commit()
        self._mail("mentioned", card, wanted, actor, _excerpt(body))
        return await self._comment(comment, actor)

    async def _own_comment(
        self, card: TodoCard, comment_id: uuid.UUID, principal: Principal
    ) -> tuple[TodoComment, uuid.UUID]:
        comment = await self.session.get(TodoComment, comment_id)
        if comment is None or comment.card_id != card.id or comment.deleted_at is not None:
            raise NotFoundError(f"comment {comment_id} not found")
        me = await self.access.me(principal)
        if me is None or comment.author_id != me:
            raise ForbiddenError("Only the author edits a comment.", code="not_comment_author")
        return comment, me

    async def edit_comment(
        self,
        card_id: uuid.UUID,
        comment_id: uuid.UUID,
        body: str,
        mentions: Sequence[uuid.UUID],
        principal: Principal,
    ) -> TodoCommentOut:
        """Change an own comment; mentions that are new get the mail."""
        card, board = await self._card(card_id, principal, lock=True, write=True)
        comment, me = await self._own_comment(card, comment_id, principal)
        wanted = list(dict.fromkeys(mentions))
        await self._check_mentions(board, wanted)
        before = {_uuid_of(m) for m in comment.mentions or []}
        comment.body = body
        comment.mentions = [str(m) for m in wanted]
        comment.edited_at = _now()
        self._touch(board, card)
        await self.session.commit()
        self._mail("mentioned", card, [m for m in wanted if m not in before], me, _excerpt(body))
        return await self._comment(comment, me)

    async def delete_comment(
        self, card_id: uuid.UUID, comment_id: uuid.UUID, principal: Principal
    ) -> None:
        """Soft-delete an own comment and remove its files."""
        card, board = await self._card(card_id, principal, lock=True, write=True)
        comment, _me = await self._own_comment(card, comment_id, principal)
        comment.deleted_at = _now()
        await self.files.delete_for_messages("todo_comment", [comment.id], actor=principal.sub)
        self._touch(board, card)
        await self.session.commit()

    async def _comment(self, comment: TodoComment, me: uuid.UUID) -> TodoCommentOut:
        persons = await person_refs(self.session, frozenset(_comment_people(comment)))
        files = await self.files.message_attachments("todo_comment", [comment.id])
        return _comment_out(comment, persons, me, files.get(comment.id, ()))

"""Internal/public comments on an application."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.applications.models import Comment
from app.modules.applications.schemas import CommentOut
from app.modules.applications.service.service_base import ApplicationsServiceBase


class CommentOps(ApplicationsServiceBase):
    """Add and list application comments."""

    async def add_comment(
        self,
        application_id: UUID,
        *,
        author: str | None,
        author_kind: str,
        body: str,
        visibility: str,
        allow_unconfirmed: bool = True,
    ) -> CommentOut:
        await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        comment = Comment(
            application_id=application_id,
            author=author,
            author_kind=author_kind,
            body=body,
            visibility=visibility,
        )
        self.session.add(comment)
        await self.session.commit()
        names = await self._author_names({author} if author else set())
        return CommentOut(
            id=comment.id,
            author=names.get(author, author) if author else None,
            authorKind=author_kind,  # type: ignore[arg-type] — validated against CHECK
            body=comment.body,
            visibility=visibility,  # type: ignore[arg-type]
            at=comment.at,
        )

    async def list_comments(
        self,
        application_id: UUID,
        *,
        include_internal: bool,
        allow_unconfirmed: bool = True,
    ) -> list[CommentOut]:
        await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        stmt = select(Comment).where(Comment.application_id == application_id)
        if not include_internal:
            stmt = stmt.where(Comment.visibility == "public")
        rows = (await self.session.scalars(stmt.order_by(Comment.at))).all()
        names = await self._author_names({c.author for c in rows if c.author})
        return [
            CommentOut(
                id=c.id,
                author=names.get(c.author, c.author) if c.author else None,
                authorKind=c.author_kind,  # type: ignore[arg-type]
                body=c.body,
                visibility=c.visibility,  # type: ignore[arg-type]
                at=c.at,
            )
            for c in rows
        ]

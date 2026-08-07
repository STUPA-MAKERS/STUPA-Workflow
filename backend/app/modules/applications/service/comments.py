"""Internal/public comments on an application."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.applications.models import Comment
from app.modules.applications.schemas import CommentOut
from app.modules.applications.service.service_base import ApplicationsServiceBase
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.shared.errors import ForbiddenError, NotFoundError


def is_comment_author(
    comment_author: str | None,
    comment_author_kind: str,
    *,
    viewer_sub: str | None,
    viewer_is_applicant: bool,
) -> bool:
    """Tell whether the viewer wrote this comment.

    An applicant comment stores no ``sub``, so the magic-link applicant of the
    application owns every applicant comment on it.
    """
    if comment_author_kind == "principal":
        return viewer_sub is not None and comment_author == viewer_sub
    return viewer_is_applicant


class CommentOps(ApplicationsServiceBase):
    """Add, list, edit and remove application comments."""

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
            isOwn=True,  # the creator is always the viewer of the 201 response
        )

    async def list_comments(
        self,
        application_id: UUID,
        *,
        include_internal: bool,
        allow_unconfirmed: bool = True,
        viewer_sub: str | None = None,
        viewer_is_applicant: bool = False,
    ) -> list[CommentOut]:
        """List the comments of one application.

        The ``viewer_*`` arguments mark the own comments of the viewer with
        ``isOwn``. A principal matches on the stored author ``sub``. The
        magic-link applicant owns every applicant comment of the own application.
        """
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
                isOwn=is_comment_author(
                    c.author,
                    c.author_kind,
                    viewer_sub=viewer_sub,
                    viewer_is_applicant=viewer_is_applicant,
                ),
            )
            for c in rows
        ]

    async def _get_comment(self, application_id: UUID, comment_id: UUID) -> Comment:
        """Load one comment of this application.

        Raises:
            NotFoundError: The comment does not exist, or it belongs to another
                application (404).
        """
        comment = (
            await self.session.execute(
                select(Comment).where(
                    Comment.id == comment_id, Comment.application_id == application_id
                )
            )
        ).scalar_one_or_none()
        if comment is None:
            raise NotFoundError(f"comment {comment_id} not found")
        return comment

    @staticmethod
    def _assert_may_write(
        comment: Comment,
        *,
        viewer_sub: str | None,
        viewer_is_applicant: bool,
        can_manage: bool,
    ) -> None:
        """Gate the edit and the delete of one comment, server-side.

        The identity comes from the session, never from the request body.

        Raises:
            ForbiddenError: The caller neither wrote the comment nor manages
                applications (403).
        """
        if can_manage:
            return
        if is_comment_author(
            comment.author,
            comment.author_kind,
            viewer_sub=viewer_sub,
            viewer_is_applicant=viewer_is_applicant,
        ):
            return
        raise ForbiddenError("Only the author or an application manager may change a comment.")

    async def _audit_comment(
        self, comment: Comment, action: AuditAction, *, actor: str
    ) -> None:
        """Record a comment mutation. ``data`` holds no comment text, only metadata."""
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type="comment",
            target_id=str(comment.id),
            data={
                "applicationId": str(comment.application_id),
                "authorKind": comment.author_kind,
                "visibility": comment.visibility,
            },
        )

    async def update_comment(
        self,
        application_id: UUID,
        comment_id: UUID,
        *,
        body: str,
        actor: str,
        viewer_sub: str | None,
        viewer_is_applicant: bool,
        can_manage: bool,
        allow_unconfirmed: bool = True,
    ) -> CommentOut:
        """Replace the body of a comment in place.

        A comment keeps no version history, so the audit log is the only record
        that the text changed. The visibility stays fixed.

        Raises:
            NotFoundError: The application or the comment does not exist (404).
            ForbiddenError: The caller is neither the author nor a manager (403).
        """
        await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        comment = await self._get_comment(application_id, comment_id)
        self._assert_may_write(
            comment,
            viewer_sub=viewer_sub,
            viewer_is_applicant=viewer_is_applicant,
            can_manage=can_manage,
        )
        comment.body = body
        await self._audit_comment(comment, AuditAction.COMMENT_UPDATE, actor=actor)
        await self.session.commit()
        names = await self._author_names({comment.author} if comment.author else set())
        return CommentOut(
            id=comment.id,
            author=names.get(comment.author, comment.author) if comment.author else None,
            authorKind=comment.author_kind,  # type: ignore[arg-type] — validated against CHECK
            body=comment.body,
            visibility=comment.visibility,  # type: ignore[arg-type]
            at=comment.at,
            isOwn=is_comment_author(
                comment.author,
                comment.author_kind,
                viewer_sub=viewer_sub,
                viewer_is_applicant=viewer_is_applicant,
            ),
        )

    async def delete_comment(
        self,
        application_id: UUID,
        comment_id: UUID,
        *,
        actor: str,
        viewer_sub: str | None,
        viewer_is_applicant: bool,
        can_manage: bool,
        allow_unconfirmed: bool = True,
    ) -> None:
        """Remove a comment for good.

        Raises:
            NotFoundError: The application or the comment does not exist (404).
            ForbiddenError: The caller is neither the author nor a manager (403).
        """
        await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        comment = await self._get_comment(application_id, comment_id)
        self._assert_may_write(
            comment,
            viewer_sub=viewer_sub,
            viewer_is_applicant=viewer_is_applicant,
            can_manage=can_manage,
        )
        await self._audit_comment(comment, AuditAction.COMMENT_DELETE, actor=actor)
        await self.session.delete(comment)
        await self.session.commit()

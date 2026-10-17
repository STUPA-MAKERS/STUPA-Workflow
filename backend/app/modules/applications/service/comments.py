"""Internal/public comments on an application.

A comment can carry files (at most five, the draft uploads of the composer). The send
binds them with ``comment_id``; they are fixed after that. The delete of a comment
removes its files with their objects. A file of a comment has no ``application_id``,
so it never shows in the attachment list of the application. An anonymized
application takes no comment files, because the retention ran once and would not
see them again.

A comment can mention members (``mentions``, principal ids). Only a caller who reads
the internal comments mentions, and only a person of `mentionable_people`; else the
write is 422 ``mention_not_member``. The create and the edit put the mentions that
they added into ``added_mentions``, and the router mails exactly those after the
commit. The applicant view never sees the list (A12, O16).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from app.modules.applications.mentions import mentionable_ids, mentionable_people
from app.modules.applications.models import Applicant, Application, Comment
from app.modules.applications.schemas import ActorOut, CommentOut
from app.modules.applications.service.service_base import ApplicationsServiceBase
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.files.drafts import bind_drafts, check_message_drafts
from app.modules.files.schemas import MessageAttachmentOut
from app.modules.files.service import FilesService
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem
from app.shared.mentions import (
    check_mentions,
    mention_error,
    mention_ids,
    new_mentions,
    stored_mentions,
    unique_mentions,
)
from app.shared.people import PersonRef, person_refs

#: The problem code of a comment with files on an anonymized application.
APPLICATION_ANONYMIZED = "application_anonymized"


def is_comment_author(
    comment_author: str | None,
    comment_author_kind: str,
    *,
    viewer_sub: str | None,
    viewer_is_applicant: bool,
) -> bool:
    """Tell whether the viewer wrote this comment.

    A principal matches on the stored author ``sub``. The magic-link applicant
    of the application owns every applicant comment on it, because an applicant
    comment stores no ``sub``. This is the same rule that ``isOwn`` uses in the
    listing, so the frontend never offers an edit that the server refuses.
    """
    if comment_author_kind == "principal":
        return viewer_sub is not None and comment_author == viewer_sub
    return viewer_is_applicant


class CommentOps(ApplicationsServiceBase):
    """Add, list, edit and remove application comments."""

    #: The mentions that the last create or edit added, for the mention mail.
    added_mentions: Sequence[UUID] = ()

    async def _checked_mentions(
        self, application_id: UUID, mentions: Sequence[UUID], *, may_mention: bool
    ) -> list[UUID]:
        """Return the mentions without duplicates, after the check.

        Raises:
            ValidationProblem: A mention by a caller who does not read the internal
                comments, or a mention outside `mentionable_people` (HTTP 422,
                ``mention_not_member``).
        """
        wanted = unique_mentions(mentions)
        if not wanted:
            return wanted
        if not may_mention:
            raise mention_error()
        check_mentions(wanted, await mentionable_ids(self.session, application_id))
        return wanted

    async def mentionable(self, application_id: UUID) -> list[PersonRef]:
        """Return the persons whom a comment on the application may mention.

        The caller checked that the viewer reads the internal comments. An
        unconfirmed guest submission answers 404, like the comment list of a
        principal.

        Raises:
            NotFoundError: The application does not exist or is unconfirmed (404).
        """
        await self._get_app(application_id, allow_unconfirmed=False)
        return await mentionable_people(self.session, application_id)

    async def _mention_refs(
        self, rows: Sequence[Comment], *, applicant_view: bool
    ) -> dict[UUID, list[PersonRef]]:
        """Resolve the mentions of the comments in one query; empty in the applicant view."""
        if applicant_view:
            return {}
        ids = {c.id: mention_ids(c.mentions) for c in rows}
        refs = await person_refs(self.session, (pid for pids in ids.values() for pid in pids))
        return {cid: [refs[pid] for pid in pids] for cid, pids in ids.items()}

    async def add_comment(
        self,
        application_id: UUID,
        *,
        author: str | None,
        author_kind: str,
        body: str,
        visibility: str,
        allow_unconfirmed: bool = True,
        attachment_ids: Sequence[UUID] = (),
        draft_token: str | None = None,
        pepper: str = "",
        mentions: Sequence[UUID] = (),
        may_mention: bool = False,
    ) -> CommentOut:
        """Add a comment and bind its files in the same transaction.

        ``may_mention`` is true when the caller reads the internal comments
        (``Access.can_see_internal``). Every mention is new, so ``added_mentions``
        holds all of them.

        Raises:
            NotFoundError: The application does not exist or is hidden (404).
            ValidationProblem: Files on an anonymized application
                (``application_anonymized``), files without a draft token, or a draft
                that is missing, expired, foreign or infected (422). A mention that
                the caller may not make (422, ``mention_not_member``).
        """
        # With files the application row is locked before the anonymized check, as
        # the anonymization locks it. Otherwise a comment that binds files while the
        # application is anonymized keeps them, because no later step looks for them.
        app = await self._get_app(
            application_id, allow_unconfirmed=allow_unconfirmed, lock=bool(attachment_ids)
        )
        if attachment_ids and await self._is_anonymized(application_id):
            raise ValidationProblem(
                "The application is anonymized and takes no files.",
                code=APPLICATION_ANONYMIZED,
                errors=[{"field": "attachmentIds", "msg": "application is anonymized"}],
            )
        wanted = await self._checked_mentions(
            application_id, mentions, may_mention=may_mention
        )
        token = await check_message_drafts(
            self.session, attachment_ids=attachment_ids, token=draft_token, pepper=pepper
        )
        comment = Comment(
            application_id=application_id,
            author=author,
            author_kind=author_kind,
            body=body,
            visibility=visibility,
            mentions=stored_mentions(wanted),
        )
        self.session.add(comment)
        if token is not None:
            await self.session.flush()
            await bind_drafts(
                self.session,
                attachment_ids=attachment_ids,
                token=token,
                pepper=pepper,
                comment_id=comment.id,
            )
        await self.session.commit()
        self.added_mentions = wanted
        info = await self._comment_author_info(app, author, author_kind)
        files = await self._comment_files([comment.id])
        refs = await self._mention_refs([comment], applicant_view=not may_mention)
        return CommentOut(
            id=comment.id,
            author=info.legacy(author) if author else None,
            authorKind=author_kind,  # type: ignore[arg-type] — validated against CHECK
            authorInfo=info,  # type: ignore[arg-type] — validated against CHECK
            body=comment.body,
            visibility=visibility,  # type: ignore[arg-type]
            at=comment.at,
            isOwn=True,  # the creator is always the viewer of the 201 response
            attachments=files.get(comment.id, []),
            mentions=refs.get(comment.id, []),
        )

    async def _is_anonymized(self, application_id: UUID) -> bool:
        """Tell whether the applicant of the application is anonymized."""
        at = await self.session.scalar(
            select(Applicant.anonymized_at).where(Applicant.application_id == application_id)
        )
        return at is not None

    async def _comment_files(
        self, ids: Sequence[UUID]
    ) -> dict[UUID, list[MessageAttachmentOut]]:
        """Return the files of the comments in one query."""
        return await FilesService(self.session).message_attachments("comment", ids)

    async def list_comments(
        self,
        application_id: UUID,
        *,
        include_internal: bool,
        allow_unconfirmed: bool = True,
        viewer_sub: str | None = None,
        viewer_is_applicant: bool = False,
        applicant_view: bool = False,
    ) -> list[CommentOut]:
        """List the comments of one application.

        The ``viewer_*`` arguments mark the own comments of the viewer with
        ``isOwn``. A principal matches on the stored author ``sub``. The
        magic-link applicant owns every applicant comment of the own application.

        In the ``applicant_view`` a comment of a member names the Gremium of the
        application as its author (A12, O16). A comment of the logged-in creator
        keeps the own name, unless the creator submitted for another email (F23)
        and the viewer is the magic-link applicant. The applicant view also gets
        no mentions (an empty list), because they are member names.
        """
        app = await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        stmt = select(Comment).where(Comment.application_id == application_id)
        if not include_internal:
            stmt = stmt.where(Comment.visibility == "public")
        rows = (await self.session.scalars(stmt.order_by(Comment.at))).all()
        actors = await self._resolve_actors(
            app,
            (c.author for c in rows),
            applicant_view=applicant_view,
            magic_link_view=viewer_is_applicant,
        )

        def _info(c: Comment) -> ActorOut:
            if c.author and c.author in actors:
                return actors[c.author]
            # An applicant comment stores no sub.
            return ActorOut(kind="applicant" if c.author_kind == "applicant" else "deleted")

        files = await self._comment_files([c.id for c in rows])
        refs = await self._mention_refs(rows, applicant_view=applicant_view)
        return [
            CommentOut(
                id=c.id,
                author=_info(c).legacy(c.author) if c.author else None,
                authorKind=c.author_kind,  # type: ignore[arg-type]
                authorInfo=_info(c),
                body=c.body,
                visibility=c.visibility,  # type: ignore[arg-type]
                at=c.at,
                isOwn=is_comment_author(
                    c.author,
                    c.author_kind,
                    viewer_sub=viewer_sub,
                    viewer_is_applicant=viewer_is_applicant,
                ),
                attachments=files.get(c.id, []),
                mentions=refs.get(c.id, []),
            )
            for c in rows
        ]

    async def _comment_author_info(
        self, app: Application, author: str | None, author_kind: str
    ) -> ActorOut:
        """Resolve the author of a comment that the viewer just wrote or changed.

        The viewer is the author, so the Gremium mask of the applicant view does
        not apply.
        """
        if not author:
            return ActorOut(kind="applicant" if author_kind == "applicant" else "deleted")
        actors = await self._resolve_actors(
            app, (author,), applicant_view=False, magic_link_view=False
        )
        return actors[author]

    async def _get_comment(self, application_id: UUID, comment_id: UUID) -> Comment:
        """Load one comment of this application.

        Raises:
            NotFoundError: The comment does not exist, or it belongs to another
                application (404). The path binds both ids, so a mismatch must
                not leak the existence of a foreign comment.
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

        The author may fix or withdraw the own comment. A principal with
        ``application.manage`` may do it for anybody, because an internal
        comment posted as public needs a fast removal. The author identity
        comes from the session, never from the request body.

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
        mentions: Sequence[UUID] | None = None,
        may_mention: bool = False,
    ) -> CommentOut:
        """Replace the body of a comment in place.

        A comment keeps no version history, so the new text overwrites the old
        one and the audit log is the only record that the text changed. The
        visibility stays fixed: a public comment is already out, and switching
        it to internal would only hide it from the applicant who read it. Use
        the delete for that case.

        ``mentions`` None keeps the stored mentions; a list replaces them after the
        same check as the create. ``added_mentions`` holds the ids that the list adds,
        so an edit never mails a person twice.

        Raises:
            NotFoundError: The application or the comment does not exist (404).
            ForbiddenError: The caller is neither the author nor a manager (403).
            ValidationProblem: A mention that the caller may not make (422,
                ``mention_not_member``).
        """
        app = await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        comment = await self._get_comment(application_id, comment_id)
        self._assert_may_write(
            comment,
            viewer_sub=viewer_sub,
            viewer_is_applicant=viewer_is_applicant,
            can_manage=can_manage,
        )
        self.added_mentions = []
        if mentions is not None:
            wanted = await self._checked_mentions(
                application_id, mentions, may_mention=may_mention
            )
            self.added_mentions = new_mentions(wanted, mention_ids(comment.mentions))
            comment.mentions = stored_mentions(wanted)
        comment.body = body
        await self._audit_comment(comment, AuditAction.COMMENT_UPDATE, actor=actor)
        await self.session.commit()
        info = await self._comment_author_info(app, comment.author, comment.author_kind)
        files = await self._comment_files([comment.id])
        refs = await self._mention_refs([comment], applicant_view=not may_mention)
        return CommentOut(
            id=comment.id,
            author=info.legacy(comment.author) if comment.author else None,
            authorKind=comment.author_kind,  # type: ignore[arg-type] — validated against CHECK
            authorInfo=info,
            body=comment.body,
            visibility=comment.visibility,  # type: ignore[arg-type]
            at=comment.at,
            isOwn=is_comment_author(
                comment.author,
                comment.author_kind,
                viewer_sub=viewer_sub,
                viewer_is_applicant=viewer_is_applicant,
            ),
            attachments=files.get(comment.id, []),
            mentions=refs.get(comment.id, []),
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
        files: FilesService | None = None,
    ) -> None:
        """Remove a comment for good, with its files.

        Until this route existed, an internal comment posted as public could
        only be removed by anonymizing the whole application. With a ``files``
        service that has the object storage, the objects of the files go too.

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
        files = files or FilesService(self.session)
        # The file rows are locked before the first audit entry, because
        # ``finalize_scan`` of an infected file locks its row first and then waits for
        # the lock of the audit chain (``FilesService.lock_for_messages``).
        await files.lock_for_messages("comment", [comment.id])
        await self._audit_comment(comment, AuditAction.COMMENT_DELETE, actor=actor)
        await files.delete_for_messages("comment", [comment.id], actor=actor)
        await self.session.delete(comment)
        await self.session.commit()

"""GDPR anonymization: blank the PII and keep the application itself.

The operation is irreversible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, or_, select, update

from app.modules.applications.models import (
    Applicant,
    Comment,
    MagicLink,
    SubmissionVersion,
)
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    _scrub_diff,
)
from app.modules.auth import sessions as auth_sessions
from app.modules.files.models import Attachment

if TYPE_CHECKING:
    from app.modules.files.service import FilesService


class AnonymizeOps(ApplicationsServiceBase):
    """Irreversible PII removal for one application (GDPR Art. 17)."""

    async def anonymize(
        self,
        application_id: UUID,
        *,
        files: FilesService | None = None,
        actor: str = "system",
        commit: bool = True,
    ) -> None:
        """Blank the PII of one application and keep the application itself.

        The method sets ``email`` and ``name`` to NULL and writes
        ``anonymized_at``. It also blanks every ``data`` field marked ``isPII`` and the
        free-text intake note of a capture (``capture_intake``).
        It removes the magic links and the attachments, the files of every comment
        (internal and public) included (GDPR Art. 17).

        With a ``files`` service the method also removes the storage objects. With
        ``None`` it deletes the attachment rows only. ``actor`` names the audit
        actor for that deletion. With ``commit=False`` the transaction stays open.
        The caller, an erasure request or the cron, then commits atomically.

        The application row is locked first, the lock that ``add_comment`` takes
        before it binds files. A comment with files therefore commits before the
        attachments are selected, or it sees the anonymization and refuses the files.

        The method also blanks:

        - the intake note of a capture, because it can name a person ("per Mail von Frau
          X"). The capture date and the capturing member stay;
        - the ``isPII`` keys of EVERY form version of the type, because a field marked as
          PII only after the submission is unknown to the pinned version, where ``is_pii``
          stays false, and its plaintext would survive the erasure;
        - every ``submission_version`` row and its diff, else the version list and the
          timeline leak the old snapshot;
        - the body of every applicant comment, because free text may hold personal data.
          Staff still reads the comments through the timeline and the comments API.

        It deletes every magic link, because a link is a direct access path to the PII and can
        live without an expiry; a delete is stronger than an expiry. It revokes the active
        applicant sessions, so no open magic-link token may read or write. It removes the
        attachments, because a receipt or a file name may hold PII. At the end it reloads the
        row, because the UPDATE expires the onupdate columns and a lazy load would do IO.
        """
        app = await self._get_app(application_id, lock=True)
        applicant = (
            await self.session.execute(
                select(Applicant).where(Applicant.application_id == application_id)
            )
        ).scalar_one_or_none()
        if applicant is not None:
            applicant.email = None
            applicant.name = None
            applicant.anonymized_at = datetime.now(UTC)
        app.capture_intake = None

        fields = await self._pinned_fields(app)
        pii_keys = {f.key for f in fields if f.is_pii}
        pii_keys |= await self._pii_keys_for_type(app.type_id)
        if pii_keys:
            app.data = {k: v for k, v in app.data.items() if k not in pii_keys}
            versions = (
                await self.session.scalars(
                    select(SubmissionVersion).where(
                        SubmissionVersion.application_id == application_id
                    )
                )
            ).all()
            for v in versions:
                v.data = {k: val for k, val in v.data.items() if k not in pii_keys}
                if v.diff is not None:
                    v.diff = _scrub_diff(v.diff, pii_keys)

        await self.session.execute(
            update(Comment)
            .where(
                Comment.application_id == application_id,
                Comment.author_kind == "applicant",
            )
            .values(body="[anonymisiert]")
        )
        await self.session.execute(
            delete(MagicLink).where(MagicLink.application_id == application_id)
        )
        await auth_sessions.revoke_applicant_sessions(
            self.session, application_id, now=datetime.now(UTC)
        )
        if files is not None:
            await files.delete_for_application(application_id, actor=actor)
        else:
            await self.session.execute(
                delete(Attachment).where(
                    or_(
                        Attachment.application_id.is_not(None)
                        & (Attachment.application_id == application_id),
                        Attachment.comment_id.in_(
                            select(Comment.id).where(Comment.application_id == application_id)
                        ),
                    )
                )
            )
        if commit:
            await self.session.commit()
            await self.session.refresh(app)
        else:
            await self.session.flush()

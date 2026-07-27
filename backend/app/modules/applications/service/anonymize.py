"""GDPR anonymization: blank the PII and keep the application itself.

The operation is irreversible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select, update

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
        ``anonymized_at``. It also blanks every ``data`` field marked ``isPII``.
        It removes the magic links and the attachments (GDPR Art. 17).

        With a ``files`` service the method also removes the storage objects. With
        ``None`` it deletes the attachment rows only. ``actor`` names the audit
        actor for that deletion. With ``commit=False`` the transaction stays open.
        The caller, an erasure request or the cron, then commits atomically.
        """
        app = await self._get_app(application_id)
        applicant = (
            await self.session.execute(
                select(Applicant).where(Applicant.application_id == application_id)
            )
        ).scalar_one_or_none()
        if applicant is not None:
            applicant.email = None
            applicant.name = None
            applicant.anonymized_at = datetime.now(UTC)

        fields = await self._pinned_fields(app)
        pii_keys = {f.key for f in fields if f.is_pii}
        # A field marked as PII only after the submission is unknown to the pinned
        # version of the form, where ``is_pii`` stays false. Union the ``isPII``
        # keys over every form version of the type. Otherwise the plaintext
        # survives the erasure, against GDPR Art. 17.
        pii_keys |= await self._pii_keys_for_type(app.type_id)
        if pii_keys:
            app.data = {k: v for k, v in app.data.items() if k not in pii_keys}
            # The PII also sits in every stored version and in its diff. Scrub
            # every ``submission_version`` row. Otherwise the version list and
            # the timeline leak the old plaintext snapshot.
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

        # A comment written by the applicant carries free text that may hold
        # personal data, so scrub the body. Staff still reads the comments through
        # the timeline and the comments API.
        await self.session.execute(
            update(Comment)
            .where(
                Comment.application_id == application_id,
                Comment.author_kind == "applicant",
            )
            .values(body="[anonymisiert]")
        )
        # A magic link is a direct access path to the PII through the mail.
        await self.session.execute(
            delete(MagicLink).where(MagicLink.application_id == application_id)
        )
        # Revoke the active applicant sessions. After the anonymization no open
        # magic-link token may read or write.
        await auth_sessions.revoke_applicant_sessions(
            self.session, application_id, now=datetime.now(UTC)
        )
        # An attachment may hold PII in the receipt or in the file name. With a
        # FilesService the code removes the database row and the storage object.
        # Without it the code removes the database rows only.
        if files is not None:
            await files.delete_for_application(application_id, actor=actor)
        else:
            await self.session.execute(
                delete(Attachment).where(Attachment.application_id == application_id)
            )
        if commit:
            await self.session.commit()
            # The UPDATE expires the onupdate columns. Reload them to avoid lazy IO.
            await self.session.refresh(app)
        else:
            await self.session.flush()

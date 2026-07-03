"""GDPR anonymization: blank PII while the application itself is kept (irreversible)."""

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
        """Blank PII (email/name → NULL, set ``anonymized_at``); the application stays.

        Also blanks ``isPII``-marked ``data`` fields and removes magic links and
        attachments (GDPR Art. 17). ``commit=False`` leaves the transaction open so
        the caller (erasure request/cron) commits atomically."""
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
        # Fields marked PII only AFTER submission are unknown to the pinned form
        # version (is_pii=False). Union isPII across ALL form versions of the type,
        # else the plaintext survives (GDPR Art. 17).
        pii_keys |= await self._pii_keys_for_type(app.type_id)
        if pii_keys:
            app.data = {k: v for k, v in app.data.items() if k not in pii_keys}
            # PII also sits in every stored version + its diff: scrub all
            # submission_version rows, else versions()/timeline leak the old
            # plaintext snapshot.
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

        # Applicant-authored comments (author_kind='applicant') carry free text that
        # may contain personal data → scrub the body. Staff keeps reading comments
        # via the timeline/comments API.
        await self.session.execute(
            update(Comment)
            .where(
                Comment.application_id == application_id,
                Comment.author_kind == "applicant",
            )
            .values(body="[anonymisiert]")
        )
        # Magic links are a direct PII access path (mail link) → remove.
        await self.session.execute(
            delete(MagicLink).where(MagicLink.application_id == application_id)
        )
        # Revoke active applicant sessions (kill switch): after anonymization no open
        # magic-link token may read or write.
        await auth_sessions.revoke_applicant_sessions(
            self.session, application_id, now=datetime.now(UTC)
        )
        # Attachments may contain PII (receipts/filenames): remove DB row + storage
        # object via the FilesService when available; otherwise only the DB rows.
        if files is not None:
            await files.delete_for_application(application_id, actor=actor)
        else:
            await self.session.execute(
                delete(Attachment).where(Attachment.application_id == application_id)
            )
        if commit:
            await self.session.commit()
            # onupdate columns are expired after the UPDATE → reload (avoids lazy IO).
            await self.session.refresh(app)
        else:
            await self.session.flush()

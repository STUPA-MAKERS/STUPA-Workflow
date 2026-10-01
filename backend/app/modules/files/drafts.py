"""Draft attachments of the wizard (Z4).

The wizard uploads a file before the application exists. Such a draft row has no
``application_id``. A draft token owns it instead. The database stores only the
HMAC of the token (``draft_token_hash``, peppered with ``MAGIC_LINK_SECRET``), never
the token.

The flow has four steps:

1. ``POST /apply/attachments`` without a token: the route checks ALTCHA for an
   anonymous caller, and ``upload`` issues a new token.
2. ``POST /apply/attachments`` with the token: the route checks the token before it
   reads the file, and ``upload`` adds a file. Each upload moves the end of the token
   and of ALL its drafts to now + ``attachment_draft_ttl_days``. One token holds at
   most ``attachment_draft_max_files`` files and ``attachment_draft_max_bytes`` bytes.
3. ``DELETE /apply/attachments/{id}`` with the token: ``delete`` removes one draft.
4. ``POST /applications`` with ``attachmentIds`` and ``draftToken``: ``bind_drafts``
   binds the files in the transaction of the create.

The token lives on its own in ``attachment_draft_token``. It stays valid until its
end, also when the owner deletes the last draft. The hourly cron
``purge_draft_attachments`` removes the expired drafts with their objects, and the
expired tokens. A draft is scanned like any other file, and it stays quarantined
until the scan is clean.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth import tokens
from app.modules.files.models import DRAFT_KEY_PREFIX, Attachment, AttachmentDraftToken
from app.modules.files.schemas import DraftAttachmentOut
from app.modules.files.service import (
    SCAN_RESULT_CLEAN,
    FilesService,
    upload_audit_data,
)
from app.modules.files.storage import StorageError
from app.shared.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ValidationProblem,
)

logger = logging.getLogger("app.files")

# The problem code when the token is unknown or expired. The wizard then starts a new
# draft (with a new ALTCHA solution) and uploads the files again.
DRAFT_TOKEN_INVALID = "draft_token_invalid"
# The problem code of the create when a listed draft is missing, expired, foreign or
# infected. The errors name each id.
DRAFT_ATTACHMENTS_MISSING = "draft_attachments_missing"
# The problem code when a token reaches its file or byte limit.
DRAFT_QUOTA_EXCEEDED = "draft_quota_exceeded"


def hash_draft_token(token: str, pepper: str) -> bytes:
    """Return the HMAC-SHA256 of a draft token for ``draft_token_hash``."""
    return tokens.hash_token(token, pepper)


def invalid_token() -> ValidationProblem:
    """Return the 422 problem for a token that is unknown or expired."""
    return ValidationProblem(
        "The draft token is unknown or expired. Upload the files again.",
        code=DRAFT_TOKEN_INVALID,
        errors=[{"field": "draftToken", "msg": "unknown or expired"}],
    )


async def _lock_token(session: AsyncSession, token_hash: bytes) -> None:
    """Serialize the uploads of one token until the end of the transaction.

    Two parallel uploads with the same token then cannot both pass the limit check.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "attachment-draft:" + token_hash.hex()},
    )


def _is_usable(attachment: Attachment, now: datetime) -> bool:
    """Tell whether a draft can still be bound: not expired and not infected.

    A draft whose scan is still pending is usable. It stays quarantined after the
    bind until the scan is clean.
    """
    if attachment.draft_expires_at is None or attachment.draft_expires_at <= now:
        return False
    if attachment.storage_key is None:
        return False
    return not (
        attachment.scanned and attachment.scan_result not in (None, SCAN_RESULT_CLEAN)
    )


class DraftAttachments:
    """Draft upload, delete and bind, on top of ``FilesService``."""

    def __init__(self, files: FilesService) -> None:
        self.files = files
        self.session = files.session
        self.settings = files.settings

    def _hash(self, token: str) -> bytes:
        return hash_draft_token(token, self.settings.magic_link_secret)

    async def token_is_valid(self, token: str, *, now: datetime | None = None) -> bool:
        """Tell whether the token was issued and has not expired.

        The check reads the token table only, so it does not depend on the drafts of
        the token. A token without drafts is valid until its end. The route calls it
        before it reads the file.
        """
        return await self._token_alive(self._hash(token), now or datetime.now(UTC))

    async def _token_alive(self, token_hash: bytes, now: datetime) -> bool:
        found = await self.session.scalar(
            select(AttachmentDraftToken.token_hash).where(
                AttachmentDraftToken.token_hash == token_hash,
                AttachmentDraftToken.expires_at > now,
            )
        )
        return found is not None

    async def upload(
        self,
        *,
        token: str | None,
        filename: str | None,
        data: bytes,
        by: str,
        field_key: str | None = None,
        is_comparison_offer: bool = False,
    ) -> DraftAttachmentOut:
        """Store a draft upload and enqueue its scan.

        ``token`` is None for the first upload. The method then issues a new token.
        The route checks ALTCHA before it calls this method. A given token must be
        issued and not expired, else the method answers 422 (``draft_token_invalid``).
        The token need not own a draft: the owner may have deleted all of them.

        The method writes an ``attachment_upload`` audit entry with ``draft: true``
        (F12) and moves the end of the token and of all its drafts.

        Raises:
            ValidationProblem: The token is unknown or expired (HTTP 422).
            PayloadTooLargeError: The file or the token quota is too large (HTTP 413).
            UnsupportedMediaTypeError: The content is not allowed (HTTP 415).
            ServiceUnavailableError: Object storage is off or failed (HTTP 503).
        """
        mime, safe_name = self.files.validate(filename, data)
        now = datetime.now(UTC)
        issued = token is None
        plain = tokens.generate_token() if token is None else token
        token_hash = self._hash(plain)
        await _lock_token(self.session, token_hash)
        if not issued and not await self._token_alive(token_hash, now):
            raise invalid_token()
        await self._check_quota(token_hash, len(data))

        attachment_id = uuid.uuid4()
        storage_key = f"{DRAFT_KEY_PREFIX}{attachment_id}/{safe_name}"
        await self.files.put_object(storage_key, data, mime)
        expires_at = now + timedelta(days=self.settings.attachment_draft_ttl_days)
        attachment = Attachment(
            id=attachment_id,
            application_id=None,
            field_key=field_key,
            filename=safe_name,
            mime=mime,
            size=len(data),
            storage_key=storage_key,
            scanned=False,
            scan_result=None,
            is_comparison_offer=is_comparison_offer,
            draft_token_hash=token_hash,
            draft_expires_at=expires_at,
        )
        self.session.add(attachment)
        await self.session.flush()
        token_row = insert(AttachmentDraftToken).values(
            token_hash=token_hash, expires_at=expires_at
        )
        await self.session.execute(
            token_row.on_conflict_do_update(
                index_elements=[AttachmentDraftToken.token_hash],
                set_={"expires_at": token_row.excluded.expires_at},
            )
        )
        # Each upload keeps the whole draft alive: all files of the token share one end.
        await self.session.execute(
            update(Attachment)
            .where(
                Attachment.application_id.is_(None),
                Attachment.draft_token_hash == token_hash,
            )
            .values(draft_expires_at=expires_at)
            .execution_options(synchronize_session=False)
        )
        await audit_record(
            self.session,
            actor=by,
            action=AuditAction.ATTACHMENT_UPLOAD,
            target_type="attachment",
            target_id=str(attachment_id),
            data=upload_audit_data(attachment),
        )
        await self.session.commit()
        await self.files.enqueue_scan(attachment_id, actor=by)
        return DraftAttachmentOut(
            id=attachment_id,
            filename=safe_name,
            mime=mime,
            size=len(data),
            scanned=False,
            is_comparison_offer=is_comparison_offer,
            draftToken=plain,
            draftExpiresAt=expires_at,
        )

    async def _check_quota(self, token_hash: bytes, size: int) -> None:
        """Enforce the file and byte limits of one token.

        Raises:
            PayloadTooLargeError: The new file would pass a limit (HTTP 413).
        """
        count, total = (
            await self.session.execute(
                select(func.count(Attachment.id), func.coalesce(func.sum(Attachment.size), 0))
                .where(
                    Attachment.application_id.is_(None),
                    Attachment.draft_token_hash == token_hash,
                )
            )
        ).one()
        max_files = self.settings.attachment_draft_max_files
        max_bytes = self.settings.attachment_draft_max_bytes
        if int(count) + 1 > max_files:
            raise PayloadTooLargeError(
                f"A draft holds at most {max_files} files.", code=DRAFT_QUOTA_EXCEEDED
            )
        if int(total) + size > max_bytes:
            raise PayloadTooLargeError(
                f"A draft holds at most {max_bytes} bytes.", code=DRAFT_QUOTA_EXCEEDED
            )

    async def delete(self, attachment_id: uuid.UUID, *, token: str, actor: str) -> None:
        """Remove one draft: the row, the object and an audit entry.

        Only the token that owns the draft may remove it. Any other case (unknown id,
        bound file, other token) gives 404, so the route is no existence oracle. An
        expired draft can still be removed. The token stays valid after the delete.

        One DELETE statement carries all the conditions. A create that binds the draft
        in parallel holds the row lock (``check_drafts``). When it commits first,
        Postgres checks the conditions again on the new row version, the row is no
        draft any more and the method gives 404. The bound file, its object and the
        audit chain stay correct.

        Raises:
            NotFoundError: The token owns no draft with this id (HTTP 404).
        """
        removed = (
            await self.session.execute(
                delete(Attachment)
                .where(
                    Attachment.id == attachment_id,
                    Attachment.application_id.is_(None),
                    Attachment.draft_token_hash == self._hash(token),
                )
                .returning(Attachment.storage_key)
                .execution_options(synchronize_session=False)
            )
        ).first()
        if removed is None:
            raise NotFoundError(f"attachment {attachment_id} not found")
        storage_key = removed.storage_key
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.ATTACHMENT_DELETE,
            target_type="attachment",
            target_id=str(attachment_id),
            data={"draft": True},
        )
        await self.session.commit()
        storage = self.files.storage
        if storage is not None and storage_key is not None:
            try:
                await storage.remove(storage_key)
            except StorageError:
                logger.warning("could not remove object for deleted draft %s", attachment_id)


async def bind_drafts(
    session: AsyncSession,
    *,
    application_id: uuid.UUID,
    attachment_ids: Sequence[uuid.UUID],
    token: str,
    pepper: str,
) -> None:
    """Bind the listed drafts of a token to a new application, without a commit.

    The caller runs this in the transaction of the create, after ``check_drafts``.
    The method sets ``application_id`` and clears both draft columns. The storage key
    stays.
    """
    if not attachment_ids:
        return
    await session.execute(
        update(Attachment)
        .where(
            Attachment.id.in_(list(attachment_ids)),
            Attachment.application_id.is_(None),
            Attachment.draft_token_hash == hash_draft_token(token, pepper),
        )
        .values(application_id=application_id, draft_token_hash=None, draft_expires_at=None)
        .execution_options(synchronize_session=False)
    )


async def check_drafts(
    session: AsyncSession,
    *,
    attachment_ids: Sequence[uuid.UUID],
    token: str,
    pepper: str,
    now: datetime | None = None,
) -> None:
    """Make sure that the token owns every listed draft and that each one is usable.

    The method locks the rows (``FOR UPDATE``) until the end of the transaction, so a
    parallel delete or purge cannot remove a draft between the check and the bind.
    A draft whose scan is still pending passes.

    Raises:
        ValidationProblem: At least one id is missing, expired, owned by another token,
            already bound or infected (HTTP 422). The errors name each such id.
    """
    moment = now or datetime.now(UTC)
    token_hash = hash_draft_token(token, pepper)
    rows = (
        await session.scalars(
            select(Attachment)
            .where(
                Attachment.id.in_(list(attachment_ids)),
                Attachment.application_id.is_(None),
                Attachment.draft_token_hash == token_hash,
            )
            .with_for_update()
        )
    ).all()
    usable = {row.id for row in rows if _is_usable(row, moment)}
    missing = [aid for aid in dict.fromkeys(attachment_ids) if aid not in usable]
    if missing:
        raise ValidationProblem(
            "Some attachments are missing, expired or infected. Upload them again.",
            code=DRAFT_ATTACHMENTS_MISSING,
            errors=[
                {"field": f"attachmentIds.{aid}", "msg": "missing, expired or infected"}
                for aid in missing
            ],
        )

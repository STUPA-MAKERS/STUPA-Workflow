"""Files service: upload, quarantine, signed URLs, scan completion.

Flow:

1. :meth:`upload` — size/MIME check (sniff != extension → 415, > 10 MB → 413), object
   into MinIO (``scanned=false``), create row, enqueue scan job. No synchronous scan.
2. Worker scans, calls :meth:`finalize_scan` — ``scanned=true`` + result; on a finding
   delete object + audit (quarantine).
3. :meth:`signed_url` — only after a clean scan returns the app-relative, authz-gated
   ``/download`` route (no signature, no expiry); otherwise 409 (still scanning) /
   410 (removed). No direct bucket access.

The service only enqueues; without the queue (no Redis) the file stays quarantined (no
block). Without storage, upload is impossible → 503.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.files.mime import MimeRejected, sanitize_filename, validate_upload
from app.modules.files.models import MAX_ATTACHMENT_BYTES, Attachment
from app.modules.files.queue import ScanQueue
from app.modules.files.scanner import ScanVerdict
from app.modules.files.schemas import AttachmentOut, SignedUrlOut
from app.modules.files.storage import ObjectStorage, StorageError
from app.settings import Settings, get_settings
from app.shared.errors import (
    ConflictError,
    GoneError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
)

logger = logging.getLogger("app.files")

SCAN_RESULT_CLEAN = "clean"


def _is_infected(attachment: Attachment) -> bool:
    """Whether a finished scan found something (!= clean)."""
    return attachment.scanned and attachment.scan_result not in (None, SCAN_RESULT_CLEAN)


class FilesService:
    """Attachment operations bound to an ``AsyncSession``."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage | None = None,
        queue: ScanQueue | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.queue = queue
        self.settings = settings or get_settings()

    @property
    def max_bytes(self) -> int:
        return min(self.settings.attachment_max_bytes, MAX_ATTACHMENT_BYTES)

    # --- upload ---
    async def upload(
        self,
        application_id: uuid.UUID,
        *,
        filename: str | None,
        data: bytes,
        by: str,
        field_key: str | None = None,
        is_comparison_offer: bool = False,
    ) -> AttachmentOut:
        """Validate the file, store in MinIO, create the row, enqueue the scan."""
        if len(data) > self.max_bytes:
            raise PayloadTooLargeError(
                f"Attachment exceeds {self.max_bytes} bytes."
            )
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")

        app = await self.session.get(Application, application_id)
        if app is None:
            raise NotFoundError(f"application {application_id} not found")

        # Deliberately no edit lock (unlike the PATCH path): attachments may be added
        # even in locked states (submitted/approved) — e.g. invoices/receipts after the
        # decision. Form data stays protected by the PATCH lock; access is still guarded
        # by the router's RBAC/applicant check.

        try:
            mime = validate_upload(filename, data)
        except MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc

        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")

        safe_name = sanitize_filename(filename)
        storage_key = f"{application_id}/{uuid.uuid4().hex}/{safe_name}"
        try:
            await self.storage.put(storage_key, data, mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc

        attachment = Attachment(
            application_id=application_id,
            field_key=field_key,
            filename=safe_name,
            mime=mime,
            size=len(data),
            storage_key=storage_key,
            scanned=False,
            scan_result=None,
            is_comparison_offer=is_comparison_offer,
        )
        self.session.add(attachment)
        await self.session.commit()

        await self._enqueue_scan(attachment.id, actor=by)
        return _attachment_out(attachment)

    async def _enqueue_scan(self, attachment_id: uuid.UUID, *, actor: str) -> None:
        """Best-effort enqueue of the scan job; without a queue the file stays quarantined."""
        if self.queue is None:
            logger.warning(
                "scan queue unavailable — attachment %s stays quarantined", attachment_id
            )
            return
        await self.queue.enqueue(attachment_id)

    async def _assert_app_visible(
        self, application_id: uuid.UUID, *, allow_unconfirmed: bool
    ) -> None:
        """Mirror the application's visibility: an unconfirmed guest submission
        (``email_confirmed_at IS NULL``) stays invisible to principals/gremium, exactly
        as ``list_applications``/``list_tasks`` hide it. Item routes without an owning
        magic-link applicant pass ``allow_unconfirmed=False`` and get 404 not 403 (no
        existence oracle), mirroring the app detail/timeline/version/comment gates. The
        owning applicant reads with the default (``allow_unconfirmed=True``)."""
        if allow_unconfirmed:
            return
        confirmed = await self.session.scalar(
            select(Application.email_confirmed_at).where(
                Application.id == application_id
            )
        )
        if confirmed is None:
            raise NotFoundError(f"application {application_id} not found")

    async def list_for_application(
        self, application_id: uuid.UUID, *, allow_unconfirmed: bool = True
    ) -> list[AttachmentOut]:
        """All attachments of an application (for the panel after reload). Oldest first.

        ``allow_unconfirmed=False`` (principal/gremium read) hides the attachments of an
        unconfirmed guest submission (404), mirroring the list semantics."""
        await self._assert_app_visible(
            application_id, allow_unconfirmed=allow_unconfirmed
        )
        rows = (
            await self.session.scalars(
                select(Attachment)
                .where(Attachment.application_id == application_id)
                .order_by(Attachment.created_at)
            )
        ).all()
        return [_attachment_out(a) for a in rows]

    # --- downloads ---
    async def get_attachment(self, attachment_id: uuid.UUID) -> Attachment:
        attachment = await self.session.get(Attachment, attachment_id)
        if attachment is None:
            raise NotFoundError(f"attachment {attachment_id} not found")
        return attachment

    async def _ready_attachment(self, attachment_id: uuid.UUID) -> Attachment:
        """Load attachment + download gates: 410 (removed/finding), 409 (scanning), 503
        (no storage). Shared by the URL and the stream route."""
        attachment = await self.get_attachment(attachment_id)
        if _is_infected(attachment) or attachment.storage_key is None:
            raise GoneError("Attachment removed (failed virus scan).")
        # FAIL-CLOSED — MUST NOT be inverted: while the ClamAV scan is not finished
        # (``scanned=False``) the download is refused (409). An unscanned object is NEVER
        # served; loosening/inverting this condition would let unscanned content be
        # downloaded.
        if not attachment.scanned:
            raise ConflictError("Attachment is still being scanned.")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        return attachment

    async def signed_url(
        self, attachment_id: uuid.UUID, *, allow_unconfirmed: bool = True
    ) -> SignedUrlOut:
        """App-relative download URL — only after a clean scan (else 409/410/503).

        No presigned MinIO URL: MinIO is on the internal Docker network without port
        publish; an S3v4-signed URL binds the (internal) host into the signature → not
        reachable from the browser. Instead the ``/download`` endpoint streams the bytes
        server-side via nginx ``/api/``.

        ``allow_unconfirmed=False`` (principal/gremium read) → 404 for an unconfirmed
        guest submission, mirroring the list semantics. The visibility gate runs BEFORE
        the quarantine gates so a hidden application does not shine through as existent
        via 409/410/503 (no existence oracle)."""
        attachment = await self.get_attachment(attachment_id)
        await self._assert_app_visible(
            attachment.application_id, allow_unconfirmed=allow_unconfirmed
        )
        await self._ready_attachment(attachment_id)
        return SignedUrlOut(
            url=f"/api/attachments/{attachment_id}/download",
            expiresIn=self.settings.attachment_url_ttl_seconds,
        )

    async def download_bytes(
        self, attachment_id: uuid.UUID, *, allow_unconfirmed: bool = True
    ) -> tuple[bytes, str, str]:
        """Fetch attachment bytes server-side from storage (for the ``/download`` stream).

        Same quarantine gates as :meth:`signed_url` (409/410/503); transient storage
        error → 503. Returns ``(bytes, filename, mime)`` for the stream response.

        ``allow_unconfirmed=False`` (principal/gremium read) → 404 for an unconfirmed
        guest submission, mirroring the list semantics; visibility gate BEFORE the
        quarantine gates (no existence oracle via 409/410/503)."""
        loaded = await self.get_attachment(attachment_id)
        await self._assert_app_visible(
            loaded.application_id, allow_unconfirmed=allow_unconfirmed
        )
        attachment = await self._ready_attachment(attachment_id)
        # Both guaranteed by _ready_attachment (else 410/503) — for the type checker.
        assert attachment.storage_key is not None
        assert self.storage is not None
        try:
            data = await self.storage.get(attachment.storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Attachment temporarily unavailable.") from exc
        return data, attachment.filename, attachment.mime

    async def download_stream(
        self, attachment_id: uuid.UUID, *, allow_unconfirmed: bool = True
    ) -> tuple[AsyncIterator[bytes], str, str, int]:
        """Like :meth:`download_bytes`, but returns a chunk iterator instead of loading
        the bytes fully into memory. The quarantine gates (409/410/503) and the
        visibility gate run unchanged BEFORE the stream starts; the storage connection is
        opened eagerly, so a transient error is still surfaced as 503 (before the
        response header).

        Returns ``(iterator, filename, mime, size)`` — ``size`` for ``Content-Length``."""
        loaded = await self.get_attachment(attachment_id)
        await self._assert_app_visible(
            loaded.application_id, allow_unconfirmed=allow_unconfirmed
        )
        attachment = await self._ready_attachment(attachment_id)
        # Both guaranteed by _ready_attachment (else 410/503) — for the type checker.
        assert attachment.storage_key is not None
        assert self.storage is not None
        try:
            stream = await self.storage.get_stream(attachment.storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Attachment temporarily unavailable.") from exc
        return stream, attachment.filename, attachment.mime, attachment.size

    async def delete(self, attachment_id: uuid.UUID, *, actor: str) -> None:
        """Delete an attachment: remove DB row + storage object (+ audit). 404 if missing.

        Access is checked by the router (A/P, edit scope); the storage object is removed
        best-effort (if already gone, the deletion still stands)."""
        attachment = await self.get_attachment(attachment_id)
        application_id = attachment.application_id
        storage_key = attachment.storage_key
        await self.session.delete(attachment)
        if self.storage is not None and storage_key is not None:
            try:
                await self.storage.remove(storage_key)
            except StorageError:
                logger.warning("could not remove object for deleted attachment %s", attachment_id)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.ATTACHMENT_DELETE,
            target_type="attachment",
            target_id=str(attachment_id),
            data={"application_id": str(application_id)},
        )
        await self.session.commit()

    async def delete_for_application(
        self, application_id: uuid.UUID, *, actor: str
    ) -> int:
        """Remove all attachments of an application (DSGVO anonymization).

        DB row + storage object per attachment (best-effort) + audit. Does not commit —
        the calling anonymization routine commits the transaction atomically."""
        rows = (
            await self.session.scalars(
                select(Attachment).where(Attachment.application_id == application_id)
            )
        ).all()
        for attachment in rows:
            storage_key = attachment.storage_key
            await self.session.delete(attachment)
            if self.storage is not None and storage_key is not None:
                try:
                    await self.storage.remove(storage_key)
                except StorageError:
                    logger.warning(
                        "could not remove object for anonymized attachment %s",
                        attachment.id,
                    )
            await audit_record(
                self.session,
                actor=actor,
                action=AuditAction.ATTACHMENT_DELETE,
                target_type="attachment",
                target_id=str(attachment.id),
                data={"application_id": str(application_id)},
            )
        return len(rows)

    # --- scan result ---
    async def finalize_scan(
        self,
        attachment_id: uuid.UUID,
        verdict: ScanVerdict,
        *,
        actor: str = "system",
    ) -> None:
        """Persist the scan result. Finding → delete object + audit (quarantine)."""
        attachment = await self.session.get(Attachment, attachment_id)
        if attachment is None:
            logger.info("scan result for unknown attachment %s — skipped", attachment_id)
            return

        attachment.scanned = True
        if verdict.clean:
            attachment.scan_result = SCAN_RESULT_CLEAN
            await self.session.commit()
            return

        signature = verdict.signature or "unknown"
        attachment.scan_result = signature
        storage_key = attachment.storage_key
        attachment.storage_key = None
        if self.storage is not None and storage_key is not None:
            try:
                await self.storage.remove(storage_key)
            except StorageError:
                # Object may already be gone; quarantine (storage_key=None) still stands.
                logger.warning("could not remove infected object for %s", attachment_id)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.ATTACHMENT_QUARANTINE,
            target_type="attachment",
            target_id=str(attachment_id),
            data={
                "application_id": str(attachment.application_id),
                "signature": signature,
            },
        )
        await self.session.commit()


def _attachment_out(attachment: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=attachment.id,
        filename=attachment.filename,
        mime=attachment.mime,
        size=attachment.size,
        scanned=attachment.scanned,
        is_comparison_offer=attachment.is_comparison_offer,
    )

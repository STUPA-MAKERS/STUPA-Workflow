"""Files service: upload, quarantine, download URLs and scan completion.

The flow has three steps.

``upload`` checks the size and the MIME type. A sniff that does not match the extension
gives 415. More than 10 MB gives 413. The method puts the object into MinIO with
``scanned=false``, creates the row and enqueues the scan job. It never scans
synchronously.

``finalize_scan`` runs after the worker scanned the object. It sets ``scanned=true`` and
the result. On a finding it deletes the object and writes an audit entry (quarantine).

``signed_url`` returns the app-relative ``/download`` route that the authorization layer
gates. It does so only after a clean scan. The route carries no signature and does not
expire. While the scan runs the method answers 409. After a removal it answers 410. There
is no direct bucket access.

The service only enqueues the scan. Without the queue (no Redis) the file stays
quarantined and nothing blocks. Without storage an upload is impossible and gives 503.
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
    """Tell whether a finished scan found something other than clean."""
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

        # There is no edit lock here, unlike on the PATCH path. A caller may add an
        # attachment even in a locked state such as submitted or approved, for example an
        # invoice or a receipt after the decision. The PATCH lock still protects the form
        # data. The RBAC and applicant check in the router still guards access.

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
        """Enqueue the scan job as best effort.

        Without a queue the file stays quarantined.
        """
        if self.queue is None:
            logger.warning(
                "scan queue unavailable — attachment %s stays quarantined", attachment_id
            )
            return
        await self.queue.enqueue(attachment_id)

    async def _assert_app_visible(
        self, application_id: uuid.UUID, *, allow_unconfirmed: bool
    ) -> None:
        """Mirror the visibility of the application.

        An unconfirmed guest submission has ``email_confirmed_at IS NULL``. It stays
        invisible to a principal or a member of the Gremium, exactly as
        ``list_applications`` and ``list_tasks`` hide it.

        An item route without an owning magic-link applicant passes
        ``allow_unconfirmed=False``. It then gets 404 instead of 403, so the API is no
        existence oracle. This mirrors the application detail, timeline, version and
        comment gates. The owning applicant reads with the default
        ``allow_unconfirmed=True``.

        Raises:
            NotFoundError: The application is an unconfirmed guest submission and
                ``allow_unconfirmed`` is false.
        """
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
        """Return all attachments of an application, oldest first.

        The frontend uses this for the panel after a reload.

        A read by a principal or a member of the Gremium passes
        ``allow_unconfirmed=False``. The method then hides the attachments of an
        unconfirmed guest submission with a 404. This mirrors the list semantics.
        """
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

    async def get_attachment(self, attachment_id: uuid.UUID) -> Attachment:
        attachment = await self.session.get(Attachment, attachment_id)
        if attachment is None:
            raise NotFoundError(f"attachment {attachment_id} not found")
        return attachment

    async def _ready_attachment(self, attachment_id: uuid.UUID) -> Attachment:
        """Load the attachment and apply the download gates.

        The URL route and the stream route share this method.

        Raises:
            GoneError: The scan found something, or the object is gone (HTTP 410).
            ConflictError: The scan is not finished yet (HTTP 409).
            ServiceUnavailableError: Object storage is off (HTTP 503).
        """
        attachment = await self.get_attachment(attachment_id)
        if _is_infected(attachment) or attachment.storage_key is None:
            raise GoneError("Attachment removed (failed virus scan).")
        # FAIL CLOSED. Do NOT invert this condition. The method refuses the download
        # with 409 while ``scanned`` is false and the ClamAV scan is not finished. The
        # API NEVER serves an unscanned object. A weaker or inverted condition would let
        # a caller download unscanned content.
        if not attachment.scanned:
            raise ConflictError("Attachment is still being scanned.")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        return attachment

    async def signed_url(
        self, attachment_id: uuid.UUID, *, allow_unconfirmed: bool = True
    ) -> SignedUrlOut:
        """Return the app-relative download URL after a clean scan.

        Any other state gives 409, 410 or 503.

        The route is no presigned MinIO URL. MinIO runs on the internal Docker network
        and publishes no port. An S3v4 signature binds the internal host, so the browser
        cannot reach such a URL. The ``/download`` endpoint streams the bytes from the
        server through nginx under ``/api/`` instead.

        A read by a principal or a member of the Gremium passes
        ``allow_unconfirmed=False``. An unconfirmed guest submission then gives 404,
        which mirrors the list semantics. The visibility gate runs BEFORE the quarantine
        gates. A hidden application must not shine through as existing over 409, 410
        or 503.
        """
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
        """Fetch the attachment bytes from storage for the ``/download`` stream.

        The method applies the same quarantine gates as ``signed_url`` (409, 410, 503). A
        transient storage error also gives 503. The visibility gate runs BEFORE the
        quarantine gates, so 409, 410 and 503 are no existence oracle.

        A read by a principal or a member of the Gremium passes
        ``allow_unconfirmed=False``. An unconfirmed guest submission then gives 404,
        which mirrors the list semantics.

        Returns:
            The bytes, the filename and the MIME type for the stream response.
        """
        loaded = await self.get_attachment(attachment_id)
        await self._assert_app_visible(
            loaded.application_id, allow_unconfirmed=allow_unconfirmed
        )
        attachment = await self._ready_attachment(attachment_id)
        # _ready_attachment guarantees both values, else it raises 410 or 503. The
        # two asserts only help the type checker.
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
        """Return a chunk iterator instead of the full bytes of ``download_bytes``.

        The quarantine gates (409, 410, 503) and the visibility gate run unchanged BEFORE
        the stream starts. The method opens the storage connection eagerly, so a
        transient error still surfaces as 503 before the response header goes out.

        A read by a principal or a member of the Gremium passes
        ``allow_unconfirmed=False``. An unconfirmed guest submission then gives 404,
        which mirrors the list semantics.

        Returns:
            The iterator, the filename, the MIME type and the size. The caller puts the
            size into ``Content-Length``.
        """
        loaded = await self.get_attachment(attachment_id)
        await self._assert_app_visible(
            loaded.application_id, allow_unconfirmed=allow_unconfirmed
        )
        attachment = await self._ready_attachment(attachment_id)
        # _ready_attachment guarantees both values, else it raises 410 or 503. The
        # two asserts only help the type checker.
        assert attachment.storage_key is not None
        assert self.storage is not None
        try:
            stream = await self.storage.get_stream(attachment.storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Attachment temporarily unavailable.") from exc
        return stream, attachment.filename, attachment.mime, attachment.size

    async def delete(self, attachment_id: uuid.UUID, *, actor: str) -> None:
        """Delete an attachment: the database row, the storage object and an audit entry.

        A missing attachment gives 404. The router checks access (A/P, edit scope). The
        method removes the storage object as best effort. If the object is already gone,
        the deletion still stands.
        """
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
        """Remove all attachments of an application for DSGVO anonymization.

        For each attachment the method deletes the database row, removes the storage
        object as best effort and writes an audit entry. It does not commit. The calling
        anonymization routine commits the transaction atomically.

        Returns:
            The number of removed attachments.
        """
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

    async def finalize_scan(
        self,
        attachment_id: uuid.UUID,
        verdict: ScanVerdict,
        *,
        actor: str = "system",
    ) -> None:
        """Persist the scan result.

        On a finding the method deletes the object and writes an audit entry
        (quarantine).
        """
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
                # The object may already be gone. The quarantine still stands, because
                # storage_key is NULL now.
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

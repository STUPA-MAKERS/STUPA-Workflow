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
from collections.abc import AsyncIterator, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.files.mime import MimeRejected, sanitize_filename, validate_upload
from app.modules.files.models import BOUND, MAX_ATTACHMENT_BYTES, Attachment
from app.modules.files.queue import ScanQueue
from app.modules.files.scanner import ScanVerdict
from app.modules.files.schemas import AttachmentOut, SignedUrlOut
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.flow.models import State
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

    def validate(self, filename: str | None, data: bytes) -> tuple[str, str]:
        """Check the size, the content and the storage of an upload.

        The application upload and the draft upload share this check.

        Returns:
            The sniffed MIME type and the sanitized file name.

        Raises:
            PayloadTooLargeError: The file is larger than ``max_bytes`` (HTTP 413).
            UnsupportedMediaTypeError: The file is empty, or its content does not match
                the allowlist or the extension (HTTP 415).
            ServiceUnavailableError: Object storage is off (HTTP 503).
        """
        if len(data) > self.max_bytes:
            raise PayloadTooLargeError(
                f"Attachment exceeds {self.max_bytes} bytes."
            )
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")
        try:
            mime = validate_upload(filename, data)
        except MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        return mime, sanitize_filename(filename)

    async def put_object(self, storage_key: str, data: bytes, mime: str) -> None:
        """Write the object to storage.

        Raises:
            ServiceUnavailableError: Storage is off or the write failed (HTTP 503).
        """
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            await self.storage.put(storage_key, data, mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc

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
        """Validate the file, store in MinIO, create the row, enqueue the scan.

        The upload writes an ``attachment_upload`` audit entry in the same transaction
        (F12). It holds the application, the field key, the MIME type and the size,
        never the file name, because a file name can hold PII.
        """
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

        mime, safe_name = self.validate(filename, data)
        storage_key = f"{application_id}/{uuid.uuid4().hex}/{safe_name}"
        await self.put_object(storage_key, data, mime)

        attachment = Attachment(
            # A client-side id: the audit entry below needs it before the commit.
            id=uuid.uuid4(),
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
        await audit_record(
            self.session,
            actor=by,
            action=AuditAction.ATTACHMENT_UPLOAD,
            target_type="attachment",
            target_id=str(attachment.id),
            data=upload_audit_data(attachment),
        )
        await self.session.commit()

        await self._enqueue_scan(attachment.id, actor=by)
        return _attachment_out(attachment)

    async def enqueue_scan(self, attachment_id: uuid.UUID, *, actor: str) -> None:
        """Enqueue the scan job of an attachment (best effort, see ``_enqueue_scan``)."""
        await self._enqueue_scan(attachment_id, actor=actor)

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
        self,
        application_id: uuid.UUID,
        *,
        allow_unconfirmed: bool = True,
        hidden: Callable[[Attachment], bool] | None = None,
    ) -> list[AttachmentOut]:
        """Return all attachments of an application, oldest first.

        The frontend uses this for the panel after a reload.

        A read by a principal or a member of the Gremium passes
        ``allow_unconfirmed=False``. The method then hides the attachments of an
        unconfirmed guest submission with a 404. This mirrors the list semantics.

        ``hidden`` removes each attachment for which it returns true. The router
        uses it for the attachments of the ``isPII`` fields (O21).
        """
        await self._assert_app_visible(
            application_id, allow_unconfirmed=allow_unconfirmed
        )
        rows = (
            await self.session.scalars(
                select(Attachment)
                .where(BOUND, Attachment.application_id == application_id)
                .order_by(Attachment.created_at)
            )
        ).all()
        return [_attachment_out(a) for a in rows if hidden is None or not hidden(a)]

    async def get_attachment(self, attachment_id: uuid.UUID) -> Attachment:
        """Load a bound attachment for an application path.

        A draft (Z4) has no application and gives 404 here, so no application route
        reads, streams or deletes it. ``application_id_of`` narrows the type of the
        result.

        Raises:
            NotFoundError: No bound attachment has this id (HTTP 404).
        """
        attachment = await self.session.get(Attachment, attachment_id)
        if attachment is None or attachment.application_id is None:
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
            application_id_of(attachment), allow_unconfirmed=allow_unconfirmed
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
            application_id_of(loaded), allow_unconfirmed=allow_unconfirmed
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
            application_id_of(loaded), allow_unconfirmed=allow_unconfirmed
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

    async def assert_editable(self, application_id: uuid.UUID) -> None:
        """Make sure that the current state of the application allows data edits.

        The router calls this before an applicant or a creator deletes an attachment.
        A delete is a data change, like a PATCH. An upload is not, so the upload route
        does not call it (Z1, O4). An application without a state passes.

        Raises:
            ConflictError: The current state has ``edit_allowed = false`` (HTTP 409).
        """
        edit_allowed = await self.session.scalar(
            select(State.edit_allowed)
            .join(Application, Application.current_state_id == State.id)
            .where(Application.id == application_id)
        )
        if edit_allowed is False:
            raise ConflictError("Application is locked for editing in its current state.")

    async def delete(self, attachment_id: uuid.UUID, *, actor: str) -> None:
        """Delete an attachment: the database row, the storage object and an audit entry.

        A missing attachment gives 404. The router checks access (A/P, edit scope) and,
        for an applicant or a creator, the state lock (``assert_editable``). The method
        removes the storage object as best effort. If the object is already gone,
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
                select(Attachment).where(
                    BOUND, Attachment.application_id == application_id
                )
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
    ) -> bool:
        """Persist the scan result.

        On a finding the method deletes the object and writes an audit entry
        (quarantine). The entry names the application of a bound file. For a draft
        (Z4) it carries ``draft: true`` instead.

        The method loads the row again by id. A row that a delete, a draft purge or
        an anonymization removed during the scan is no error: the method skips it and
        returns False.

        Returns:
            True when the result was stored, False when the row is gone.
        """
        attachment = await self.session.get(
            Attachment, attachment_id, populate_existing=True
        )
        if attachment is None:
            logger.info("scan result for unknown attachment %s — skipped", attachment_id)
            return False

        attachment.scanned = True
        if verdict.clean:
            attachment.scan_result = SCAN_RESULT_CLEAN
            return await self._commit_scan(attachment_id)

        signature = verdict.signature or "unknown"
        attachment.scan_result = signature
        storage_key = attachment.storage_key
        attachment.storage_key = None
        owner: dict[str, object] = (
            {"application_id": str(attachment.application_id)}
            if attachment.application_id is not None
            else {"draft": True}
        )
        if not await self._commit_scan(
            attachment_id, actor=actor, quarantine={**owner, "signature": signature}
        ):
            return False
        if self.storage is not None and storage_key is not None:
            try:
                await self.storage.remove(storage_key)
            except StorageError:
                # The object may already be gone. The quarantine still stands, because
                # storage_key is NULL now.
                logger.warning("could not remove infected object for %s", attachment_id)
        return True

    async def _commit_scan(
        self,
        attachment_id: uuid.UUID,
        *,
        actor: str = "system",
        quarantine: dict[str, object] | None = None,
    ) -> bool:
        """Commit the scan result, and tolerate a row that is gone since the load.

        With ``quarantine`` the method first writes the quarantine audit entry with
        this data. The audit write flushes the attachment UPDATE, so the same guard
        covers it: a row that a parallel delete, purge or anonymization removed gives
        False there too, and the rollback also drops the audit entry.

        Returns:
            True after the commit, False when the UPDATE found no row.
        """
        try:
            if quarantine is not None:
                await audit_record(
                    self.session,
                    actor=actor,
                    action=AuditAction.ATTACHMENT_QUARANTINE,
                    target_type="attachment",
                    target_id=str(attachment_id),
                    data=quarantine,
                )
            await self.session.commit()
        except StaleDataError:
            await self.session.rollback()
            logger.info("attachment %s removed during the scan — skipped", attachment_id)
            return False
        return True


def application_id_of(attachment: Attachment) -> uuid.UUID:
    """Return the application of a bound attachment.

    ``get_attachment`` loads bound rows only. This helper narrows the type for the
    callers and fails closed with 404 if a draft ever reaches an application path.

    Raises:
        NotFoundError: The attachment is a draft (HTTP 404).
    """
    if attachment.application_id is None:
        raise NotFoundError(f"attachment {attachment.id} not found")
    return attachment.application_id


def upload_audit_data(attachment: Attachment) -> dict[str, object]:
    """Build the ``attachment_upload`` audit data.

    The audit chain is append-only, and anonymization cannot remove a row from it.
    Thus the data holds no client text: not the file name (PII) and not the raw
    ``field_key``. The caller sends ``field_key`` as free text, so the data records
    only whether the upload has one (``hasFieldKey``).
    """
    owner: dict[str, object] = (
        {"application_id": str(attachment.application_id)}
        if attachment.application_id is not None
        else {"draft": True}
    )
    return {
        **owner,
        "hasFieldKey": attachment.field_key is not None,
        "isComparisonOffer": attachment.is_comparison_offer,
        "mime": attachment.mime,
        "size": attachment.size,
    }


def _attachment_out(attachment: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=attachment.id,
        filename=attachment.filename,
        mime=attachment.mime,
        size=attachment.size,
        scanned=attachment.scanned,
        is_comparison_offer=attachment.is_comparison_offer,
    )

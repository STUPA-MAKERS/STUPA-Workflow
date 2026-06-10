"""files-Service (T-13): Upload, Quarantäne, signierte URLs, Scan-Abschluss.

Ablauf (security.md §6):

1. :meth:`upload` — Größen-/MIME-Prüfung (Sniff ≠ Endung → 415, > 10 MB → 413), Objekt
   in MinIO (``scanned=false``), Zeile anlegen, Scan-Job enqueuen. Kein synchroner Scan.
2. Worker scannt, ruft :meth:`finalize_scan` — ``scanned=true`` + Ergebnis; bei Befund
   Objekt löschen + Audit (Quarantäne).
3. :meth:`signed_url` — kurzlebige MinIO-URL **nur** nach sauberem Scan; sonst 409
   (läuft noch) / 410 (entfernt). Kein direkter Bucket-Zugriff.

Der Service *enqueued* nur; fehlt die Queue (kein Redis), bleibt die Datei in
Quarantäne (kein Block). Fehlt der Storage, ist der Upload nicht möglich → 503.
"""

from __future__ import annotations

import logging
import uuid

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
    """Abgeschlossener Scan mit Befund (≠ clean)."""
    return attachment.scanned and attachment.scan_result not in (None, SCAN_RESULT_CLEAN)


class FilesService:
    """An eine ``AsyncSession`` gebundene Anhang-Operationen."""

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

    # ----------------------------------------------------------------- upload #
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
        """Datei prüfen, in MinIO ablegen, Zeile anlegen, Scan enqueuen."""
        if len(data) > self.max_bytes:
            raise PayloadTooLargeError(
                f"Attachment exceeds {self.max_bytes} bytes."
            )
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")

        app = await self.session.get(Application, application_id)
        if app is None:
            raise NotFoundError(f"application {application_id} not found")

        # Edit-Lock wie T-12-PATCH: in einem gesperrten State (``edit_allowed=false``,
        # z. B. eingereicht/entschieden) sind keine neuen Anhänge erlaubt → 409.
        if app.current_state_id is not None:
            state = await self.session.get(State, app.current_state_id)
            if state is not None and not state.edit_allowed:
                raise ConflictError(
                    "Application is locked for editing in its current state."
                )

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
        """Scan-Job best-effort enqueuen; ohne Queue bleibt die Datei in Quarantäne."""
        if self.queue is None:
            logger.warning(
                "scan queue unavailable — attachment %s stays quarantined", attachment_id
            )
            return
        await self.queue.enqueue(attachment_id)

    async def list_for_application(
        self, application_id: uuid.UUID
    ) -> list[AttachmentOut]:
        """Alle Anhänge eines Antrags (für das Panel nach Reload). Älteste zuerst."""
        rows = (
            await self.session.scalars(
                select(Attachment)
                .where(Attachment.application_id == application_id)
                .order_by(Attachment.created_at)
            )
        ).all()
        return [_attachment_out(a) for a in rows]

    # -------------------------------------------------------------- downloads #
    async def get_attachment(self, attachment_id: uuid.UUID) -> Attachment:
        attachment = await self.session.get(Attachment, attachment_id)
        if attachment is None:
            raise NotFoundError(f"attachment {attachment_id} not found")
        return attachment

    async def signed_url(self, attachment_id: uuid.UUID) -> SignedUrlOut:
        """Kurzlebige Download-URL — nur nach sauberem Scan (sonst 409/410/503)."""
        attachment = await self.get_attachment(attachment_id)
        if _is_infected(attachment) or attachment.storage_key is None:
            raise GoneError("Attachment removed (failed virus scan).")
        if not attachment.scanned:
            raise ConflictError("Attachment is still being scanned.")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            url = self.storage.presigned_get_url(
                attachment.storage_key,
                expires_seconds=self.settings.attachment_url_ttl_seconds,
                download_name=attachment.filename,
            )
        except StorageError as exc:
            raise ServiceUnavailableError("Could not sign download URL.") from exc
        return SignedUrlOut(url=url, expiresIn=self.settings.attachment_url_ttl_seconds)

    async def delete(self, attachment_id: uuid.UUID, *, actor: str) -> None:
        """Anhang löschen: DB-Zeile + Storage-Objekt entfernen (+ Audit). 404 fehlt.

        Zugriff prüft der Router (A/P, edit-Scope); das Storage-Objekt wird
        best-effort entfernt (fehlt es bereits, gilt die Löschung trotzdem)."""
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

    # ------------------------------------------------------------ scan result #
    async def finalize_scan(
        self,
        attachment_id: uuid.UUID,
        verdict: ScanVerdict,
        *,
        actor: str = "system",
    ) -> None:
        """Scan-Ergebnis persistieren. Befund → Objekt löschen + Audit (Quarantäne)."""
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
                # Objekt evtl. schon weg; Quarantäne (storage_key=None) gilt trotzdem.
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

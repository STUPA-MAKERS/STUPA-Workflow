"""arq-Worker-Task: ClamAV-Scan eines Anhangs (T-13, security.md §6).

``scan_attachment`` lädt das Objekt aus MinIO, scannt es über ClamAV und schreibt das
Ergebnis via :meth:`FilesService.finalize_scan` zurück (``scanned=true``; bei Befund →
Objekt gelöscht + Audit/Quarantäne). Transiente Storage-/Scanner-Fehler → ``arq.Retry``
mit linearem Backoff bis ``scan_max_tries``, danach »dead« (geloggt, kein Endlos-Requeue).
Idempotenz trägt der Job-Key (``scan:<id>``); ein erneuter Lauf auf bereits gescanntem
Anhang ist harmlos (überschreibt dasselbe Ergebnis).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.files.models import Attachment
from app.modules.files.scanner import ScannerError, build_scanner
from app.modules.files.service import FilesService
from app.modules.files.storage import StorageError, build_object_storage
from app.settings import Settings, load_settings

logger = logging.getLogger("app.files")


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = load_settings()
    ctx["settings"] = settings
    ctx["scanner"] = build_scanner(settings)
    ctx["object_storage"] = build_object_storage(settings)


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """DB-Sessionmaker (in Tests via ``ctx['files_sessionmaker']`` injizierbar)."""
    maker = ctx.get("files_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


async def scan_attachment(ctx: dict[str, Any], attachment_id: str) -> str:
    """Anhang scannen + Ergebnis persistieren. Retry bei transientem Fehler."""
    settings: Settings = ctx["settings"]
    scanner = ctx.get("scanner")
    storage = ctx.get("object_storage")
    if scanner is None or storage is None:
        logger.warning(
            "scan skipped (attachment=%s) — clamav/storage not configured", attachment_id
        )
        return "skipped"

    aid = UUID(attachment_id)
    maker = _sessionmaker(ctx)
    async with maker() as session:
        attachment = await session.get(Attachment, aid)
        if attachment is None or attachment.storage_key is None:
            logger.info("scan target %s gone — skipped", attachment_id)
            return "gone"
        try:
            data = await storage.get(attachment.storage_key)
            verdict = await scanner.scan(data)
        except (StorageError, ScannerError) as exc:
            return _retry_or_dead(ctx, settings, attachment_id, exc)
        await FilesService(session, storage=storage, settings=settings).finalize_scan(
            aid, verdict, actor="system"
        )
    return "clean" if verdict.clean else "infected"


def _retry_or_dead(
    ctx: dict[str, Any], settings: Settings, attachment_id: str, exc: Exception
) -> str:
    """Backoff-Retry bis ``scan_max_tries``; danach »dead« (kein Endlos-Requeue)."""
    job_try = int(ctx.get("job_try", 1))
    if job_try >= settings.scan_max_tries:
        logger.error(
            "scan failed permanently after %s tries (attachment=%s): %s",
            job_try,
            attachment_id,
            type(exc).__name__,
        )
        return "dead"
    defer = settings.scan_retry_backoff_seconds * job_try
    logger.warning(
        "scan failed (try=%s, retry in %ss, attachment=%s): %s",
        job_try,
        defer,
        attachment_id,
        type(exc).__name__,
    )
    raise Retry(defer=defer) from exc

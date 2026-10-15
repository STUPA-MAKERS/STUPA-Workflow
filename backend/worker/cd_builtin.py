"""arq worker task: turn the vendored CD logos into uploads once per worker start.

`on_startup` enqueues `migrate_builtin_cd_logos`, so the conversion runs in a job
slot and never delays the start of the worker. The job is idempotent and holds an
advisory lock (`app.modules.admin.cd_builtin.convert`), so two workers that start
together do the work once. An object storage error retries with a linear backoff
up to `_MAX_TRIES`. After the last try the job logs the error and gives up; the
next worker start tries again.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.admin.cd_builtin.convert import convert_builtin_cd_logos
from app.modules.files.storage import StorageError
from app.shared.errors import ServiceUnavailableError

logger = logging.getLogger("app.admin.cd_builtin")

JOB_NAME: Final[str] = "migrate_builtin_cd_logos"
_MAX_TRIES: Final[int] = 5
_RETRY_STEP_SECONDS: Final[int] = 60


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['cd_builtin_sessionmaker']`)."""
    maker = ctx.get("cd_builtin_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


async def migrate_builtin_cd_logos(ctx: dict[str, Any]) -> str:
    """Convert every vendored CD logo into an upload.

    The object storage comes from `ctx['object_storage']`, which the protocol
    start-up builds.

    Returns:
        ``"busy"`` when another runner holds the lock, ``"failed"`` after the last
        failed try, else a short summary of the run.

    Raises:
        Retry: The object storage failed and tries remain.
    """
    try:
        async with _sessionmaker(ctx)() as session:
            result = await convert_builtin_cd_logos(session, ctx.get("object_storage"))
    except (StorageError, ServiceUnavailableError) as exc:
        tries = int(ctx.get("job_try", 1))
        if tries < _MAX_TRIES:
            raise Retry(defer=tries * _RETRY_STEP_SECONDS) from exc
        logger.warning("builtin CD logo conversion failed after %d tries: %s", tries, exc)
        return "failed"
    if result.skipped:
        return "busy"
    return (
        f"converted {result.logos} logos in {result.variants} variants, "
        f"renamed {result.renamed}"
    )


async def on_startup(ctx: dict[str, Any]) -> None:
    """Enqueue the conversion once per worker start."""
    redis = ctx.get("redis")
    if redis is None:
        return
    await redis.enqueue_job(JOB_NAME)

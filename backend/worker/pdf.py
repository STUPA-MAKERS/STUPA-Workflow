"""arq worker task: render an application PDF.

`render_pdf` builds the `RenderPipeline` (pytex + MinIO) from the `ctx` dependencies
and renders a `render_job` end to end. A transient error (pytex 5xx, transport,
storage) raises `arq.Retry` with a linear backoff up to `pdf_max_tries`. After the last
try the task marks the job `failed` for good, so it never requeues again. Idempotency
comes from the `_job_id` (`render:<id>`) at enqueue and from the job status. A `done`
job does not render again.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.files.storage import build_object_storage
from app.modules.pdf.pytex_client import build_pytex_client
from app.modules.pdf.render import RenderPipeline, RenderRetry
from app.settings import Settings, load_settings

logger = logging.getLogger("app.pdf")


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = load_settings()
    ctx["settings"] = settings
    ctx["pytex_client"] = build_pytex_client(settings)
    ctx["object_storage"] = build_object_storage(settings)


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['pdf_sessionmaker']`)."""
    maker = ctx.get("pdf_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _pipeline(ctx: dict[str, Any]) -> RenderPipeline:
    return RenderPipeline(
        sessionmaker=_sessionmaker(ctx),
        pytex=ctx["pytex_client"],
        storage=ctx.get("object_storage"),
    )


async def render_pdf(ctx: dict[str, Any], job_id: str) -> str:
    """Process one render job.

    A transient error retries with a linear backoff up to `pdf_max_tries`.

    Returns:
        The status of the pipeline run, or `"dead"` after the last failed try.
    """
    settings: Settings = ctx["settings"]
    pipeline = _pipeline(ctx)
    jid = UUID(job_id)
    try:
        return await pipeline.run(jid)
    except RenderRetry as exc:
        job_try = int(ctx.get("job_try", 1))
        if job_try >= settings.pdf_max_tries:
            logger.error(
                "render failed permanently after %s tries (job=%s): %s",
                job_try,
                job_id,
                exc,
            )
            await pipeline.mark_failed(jid, "render_unavailable")
            return "dead"
        defer = settings.pdf_retry_backoff_seconds * job_try
        logger.warning(
            "render failed (try=%s, retry in %ss, job=%s): %s",
            job_try,
            defer,
            job_id,
            exc,
        )
        raise Retry(defer=defer) from exc

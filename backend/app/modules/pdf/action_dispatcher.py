"""Flow-action dispatcher with an ``exportPdf`` handler.

The flow engine calls ``ActionDispatcher.dispatch(actions)`` after the commit. This
dispatcher handles ``exportPdf``. It creates a ``render_job`` and enqueues it for the
worker. ``DispatchedAction.idempotency_key`` makes the creation idempotent, so one
status event never renders twice. The dispatcher only logs the other action types.

``ChainActionDispatcher`` chains several dispatchers, for example notify and
``exportPdf``. The app injects one single dispatcher. Each dispatcher of the chain
ignores the types it does not handle.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.flow.dispatch import ActionDispatcher, DispatchedAction
from app.modules.pdf.queue import RenderQueue, render_queue_from_pool
from app.modules.pdf.service import PdfService
from app.shared.errors import NotFoundError

logger = logging.getLogger("app.pdf")


@dataclass(slots=True)
class PdfActionDispatcher:
    """``ActionDispatcher`` for ``exportPdf`` (other types are a no-op log)."""

    sessionmaker: async_sessionmaker[AsyncSession]
    queue: RenderQueue | None

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for action in actions:
            if action.type != "exportPdf":
                logger.info(
                    "flow action not handled by pdf-dispatcher (type=%s key=%s)",
                    action.type,
                    action.idempotency_key,
                )
                continue
            await self._dispatch_export(action)

    async def _dispatch_export(self, action: DispatchedAction) -> None:
        async with self.sessionmaker() as session:
            try:
                job = await PdfService(session).create_application_job(
                    action.application_id, idempotency_key=action.idempotency_key
                )
            except NotFoundError:
                logger.warning(
                    "exportPdf skipped — application %s gone (key=%s)",
                    action.application_id,
                    action.idempotency_key,
                )
                return
            await session.commit()
        if self.queue is not None:
            await self.queue.enqueue(job.id)


@dataclass(slots=True)
class ChainActionDispatcher:
    """Call several dispatchers in order (notify + exportPdf …)."""

    dispatchers: Sequence[ActionDispatcher]

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for dispatcher in self.dispatchers:
            await dispatcher.dispatch(actions)


def build_pdf_dispatcher(pool: object) -> PdfActionDispatcher:
    """Build the dispatcher from the optional arq pool (app wiring)."""
    return PdfActionDispatcher(
        get_sessionmaker(),
        render_queue_from_pool(pool),  # type: ignore[arg-type]
    )

"""Flow-Action-Dispatcher mit ``exportPdf``-Handler (T-20 erfüllt das T-14-Interface).

Die Flow-Engine (T-14) ruft nach Commit ``ActionDispatcher.dispatch(actions)``. Dieser
Dispatcher behandelt ``exportPdf``: er legt einen ``render_job`` an (idempotent über
``DispatchedAction.idempotency_key`` → ein Status-Event erzeugt **keinen** Doppel-Render)
und enqueued ihn (Worker rendert). Andere Action-Typen werden nur protokolliert.

:class:`ChainActionDispatcher` verkettet mehrere Dispatcher (notify **und** exportPdf),
da die App nur **einen** Dispatcher injizieren kann; jeder ignoriert die Typen, die er
nicht kennt.
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
    """``ActionDispatcher``-Implementierung für ``exportPdf`` (sonst No-op-Log)."""

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
    """Mehrere Dispatcher der Reihe nach aufrufen (notify + exportPdf …)."""

    dispatchers: Sequence[ActionDispatcher]

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for dispatcher in self.dispatchers:
            await dispatcher.dispatch(actions)


def build_pdf_dispatcher(pool: object) -> PdfActionDispatcher:
    """Dispatcher aus dem (optionalen) arq-Pool bauen — App-Wiring (main.py)."""
    return PdfActionDispatcher(
        get_sessionmaker(),
        render_queue_from_pool(pool),  # type: ignore[arg-type]
    )

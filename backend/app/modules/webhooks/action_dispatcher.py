"""Flow-Action-Handler ``webhook`` (T-19 erfüllt das T-14-Dispatch-Interface).

Die Flow-Engine ruft nach Commit ``ActionDispatcher.dispatch(actions)``. Dieser
Dispatcher behandelt ``webhook``-Actions: er ermittelt das Domain-Event und fächert es
über :meth:`WebhookService.dispatch_event` an alle abonnierten Webhooks auf (eigenes
Event-System wird **nicht** aufgebaut — angedockt an den bestehenden Action-Dispatch).

``DispatchedAction.idempotency_key`` ist stabil über (Antrag, Status-Event, Position,
Typ) → er bildet die Idempotenz-Basis der Delivery (kein Doppelversand bei Worker-/
Flow-Retry, flows §9.3).

Mehrere Handler werden über ``app.modules.pdf.action_dispatcher.ChainActionDispatcher``
(T-20) verkettet — eine Transition kann so gleichzeitig ``notify`` (T-18), ``exportPdf``
(T-20) und ``webhook`` (T-19) auslösen (kein zweites Event-System).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.flow.dispatch import DispatchedAction
from app.modules.webhooks.queue import WebhookQueue, webhook_queue_from_pool
from app.modules.webhooks.service import WebhookService
from app.settings import Settings, get_settings

logger = logging.getLogger("app.webhooks")


@dataclass(slots=True)
class WebhookActionDispatcher:
    """`ActionDispatcher`-Implementierung für `webhook` (sonst No-op)."""

    sessionmaker: async_sessionmaker[AsyncSession]
    queue: WebhookQueue | None
    settings: Settings

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for action in actions:
            if action.type != "webhook":
                continue
            await self._dispatch_webhook(action)

    async def _dispatch_webhook(self, action: DispatchedAction) -> None:
        event = action.params.get("event")
        if not event:
            logger.warning(
                "webhook action without 'event' (key=%s) — skipped",
                action.idempotency_key,
            )
            return
        payload: dict[str, object] = {
            "event": str(event),
            "applicationId": str(action.application_id),
        }
        extra = action.params.get("payload")
        if isinstance(extra, dict):
            payload.update(extra)
        async with self.sessionmaker() as session:
            service = WebhookService(session, self.settings, queue=self.queue)
            await service.dispatch_event(
                str(event),
                payload=payload,
                idempotency_base=action.idempotency_key,
            )


def build_webhook_dispatcher(pool: object) -> WebhookActionDispatcher:
    """Dispatcher aus dem (optionalen) arq-Pool bauen — App-Wiring (main.py)."""
    return WebhookActionDispatcher(
        get_sessionmaker(),
        webhook_queue_from_pool(pool),  # type: ignore[arg-type]
        get_settings(),
    )

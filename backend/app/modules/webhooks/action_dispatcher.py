"""Flow action handler for `webhook`.

The flow engine calls `ActionDispatcher.dispatch(actions)` after the commit. This
dispatcher handles `webhook` actions. It resolves the domain event and fans it out with
`WebhookService.dispatch_event` to every subscribed webhook. There is no separate event
system. The dispatcher hooks into the existing action dispatch.

`DispatchedAction.idempotency_key` is stable over the application, the status event, the
position and the action type. It is the idempotency base of the delivery. A worker retry
or a flow retry therefore sends nothing twice.

`ChainActionDispatcher` chains several handlers. One transition can therefore trigger
`notify`, `exportPdf` and `webhook` at the same time.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.flow.dispatch import DispatchedAction
from app.modules.webhooks.queue import WebhookQueue, webhook_queue_from_pool
from app.modules.webhooks.service import WebhookService
from app.settings import Settings, get_settings

logger = logging.getLogger("app.webhooks")

_TRANSITION_EVENT = "application.transition"


@dataclass(slots=True)
class WebhookActionDispatcher:
    """Handle `webhook` flow actions and ignore every other action type."""

    sessionmaker: async_sessionmaker[AsyncSession]
    queue: WebhookQueue | None
    settings: Settings

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for action in actions:
            if action.type != "webhook":
                continue
            await self._dispatch_webhook(action)

    async def _dispatch_webhook(self, action: DispatchedAction) -> None:
        webhook_id = action.params.get("webhookId")
        if not webhook_id:
            logger.warning(
                "webhook action without 'webhookId' (key=%s) — skipped",
                action.idempotency_key,
            )
            return
        try:
            target = UUID(str(webhook_id))
        except ValueError:
            logger.warning(
                "webhook action with invalid webhookId %r — skipped", webhook_id
            )
            return
        payload: dict[str, object] = {
            "event": _TRANSITION_EVENT,
            "applicationId": str(action.application_id),
            "transitionId": str(action.transition_id),
            "statusEventId": str(action.status_event_id),
        }
        async with self.sessionmaker() as session:
            service = WebhookService(session, self.settings, queue=self.queue)
            await service.dispatch_to_webhook(
                target,
                event=_TRANSITION_EVENT,
                payload=payload,
                idempotency_base=action.idempotency_key,
            )


def build_webhook_dispatcher(pool: object) -> WebhookActionDispatcher:
    """Build the dispatcher from the optional arq pool for the app wiring in `main.py`."""
    return WebhookActionDispatcher(
        get_sessionmaker(),
        webhook_queue_from_pool(pool),  # type: ignore[arg-type]
        get_settings(),
    )

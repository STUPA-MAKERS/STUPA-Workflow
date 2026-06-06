"""Flow-Action-Dispatcher mit `notify`-Handler (T-18 erfüllt das T-14-Interface).

Die Flow-Engine (T-14) ruft nach Commit ``ActionDispatcher.dispatch(actions)``. Dieser
Dispatcher behandelt ``notify``-Actions: er rendert die Mail(s) und legt sie via
Mail-Queue ab (Worker sendet). Andere Worker-Action-Typen (``webhook`` etc.) gehören
zu Folge-Tasks und werden hier nur protokolliert — nicht verworfen, nicht enqueued.

``DispatchedAction.idempotency_key`` ist stabil über (Antrag, Status-Event, Position,
Typ) → er dient als Idempotenz-Basis, damit ein Worker-Retry **keinen** Doppelversand
erzeugt (flows §9.3).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.applications.models import Application
from app.modules.flow.dispatch import DispatchedAction
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.settings import Settings, get_settings

logger = logging.getLogger("app.notifications")


@dataclass(slots=True)
class NotificationActionDispatcher:
    """`ActionDispatcher`-Implementierung für `notify` (sonst No-op-Log)."""

    sessionmaker: async_sessionmaker[AsyncSession]
    queue: MailQueue | None
    settings: Settings

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for action in actions:
            if action.type != "notify":
                logger.info(
                    "flow action not handled by notify-dispatcher (type=%s key=%s)",
                    action.type,
                    action.idempotency_key,
                )
                continue
            await self._dispatch_notify(action)

    async def _dispatch_notify(self, action: DispatchedAction) -> None:
        async with self.sessionmaker() as session:
            app_type_id = await session.scalar(
                select(Application.type_id).where(Application.id == action.application_id)
            )
            context: dict[str, object] = {"applicationId": str(action.application_id)}
            extra = action.params.get("context")
            if isinstance(extra, dict):
                context.update(extra)
            raw_lang = action.params.get("lang")
            lang = str(raw_lang) if raw_lang else None
            service = NotificationService(
                session, queue=self.queue, settings=self.settings
            )
            await service.handle_notify_action(
                action.params,
                application_id=action.application_id,
                application_type_id=app_type_id,
                context=context,
                lang=lang,
                idempotency_base=action.idempotency_key,
            )


def build_notify_dispatcher(pool: object) -> NotificationActionDispatcher:
    """Dispatcher aus dem (optionalen) arq-Pool bauen — App-Wiring (main.py)."""
    return NotificationActionDispatcher(
        get_sessionmaker(),
        mail_queue_from_pool(pool),  # type: ignore[arg-type]
        get_settings(),
    )

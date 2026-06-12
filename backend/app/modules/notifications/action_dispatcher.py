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
from app.modules.flow.models import State
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
            if action.type == "notify":
                await self._dispatch_notify(action)
            elif action.type == "taskNotify":
                await self._dispatch_task(action)
            else:
                logger.info(
                    "flow action not handled by notify-dispatcher (type=%s key=%s)",
                    action.type,
                    action.idempotency_key,
                )

    async def _dispatch_notify(self, action: DispatchedAction) -> None:
        async with self.sessionmaker() as session:
            app_type_id, current_state_id, app_data = (
                await session.execute(
                    select(
                        Application.type_id,
                        Application.current_state_id,
                        Application.data,
                    ).where(Application.id == action.application_id)
                )
            ).first() or (None, None, None)
            # Antragstitel mitgeben (#4): Templates/Builtin nennen, WORUM es geht.
            title = (app_data or {}).get("title")
            context: dict[str, object] = {
                "applicationId": str(action.application_id),
                "applicationTitle": title.strip()
                if isinstance(title, str)
                else "",
            }
            raw_lang = action.params.get("lang")
            lang = str(raw_lang) if raw_lang else None
            # ``status`` (Label des aktuellen States) bereitstellen — das Default-/Status-
            # Template referenziert ``{{ status }}``; ohne Wert scheitert StrictUndefined.
            if current_state_id is not None:
                label_i18n = await session.scalar(
                    select(State.label_i18n).where(State.id == current_state_id)
                )
                if isinstance(label_i18n, dict) and label_i18n:
                    context["status"] = (
                        label_i18n.get(lang or self.settings.mail_default_lang)
                        or next(iter(label_i18n.values()))
                    )
            extra = action.params.get("context")
            if isinstance(extra, dict):
                context.update(extra)
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


    async def _dispatch_task(self, action: DispatchedAction) -> None:
        """Task-Mail (#4-3): Antrag hat einen State erreicht, in dem die Empfänger
        handeln können — Empfänger werden zur Versandzeit aufgelöst (Task-Semantik)."""
        from app.modules.notifications.recipients import (
            actionable_principal_emails,
            state_actionable,
        )

        async with self.sessionmaker() as session:
            row = (
                await session.execute(
                    select(
                        Application.data,
                        Application.current_state_id,
                        Application.gremium_id,
                    ).where(Application.id == action.application_id)
                )
            ).first()
            if row is None:
                return
            data, state_id, gremium_id = row
            state = (
                await session.scalar(select(State).where(State.id == state_id))
                if state_id is not None
                else None
            )
            # Task-Mail nur, wenn am neuen State wirklich gehandelt werden kann (#9):
            # vote-State oder ≥1 manueller Übergang mit requiresAction — sonst ist
            # "du kannst handeln" schlicht falsch (reiner Durchgangs-/End-State).
            if not await state_actionable(session, state):
                return
            recipients = await actionable_principal_emails(
                session, state=state, gremium_id=gremium_id
            )
            if not recipients:
                return
            title = (data or {}).get("title")
            status_label = ""
            if (
                state is not None
                and isinstance(state.label_i18n, dict)
                and state.label_i18n
            ):
                status_label = state.label_i18n.get(
                    self.settings.mail_default_lang
                ) or next(iter(state.label_i18n.values()))
            service = NotificationService(
                session, queue=self.queue, settings=self.settings
            )
            await service.send_kind_mail(
                recipients,
                kind="task",
                template_key="task_new",
                builtin_subject=_BUILTIN_TASK_SUBJECT,
                builtin_body=_BUILTIN_TASK_BODY,
                context={
                    "applicationId": str(action.application_id),
                    "applicationTitle": title.strip()
                    if isinstance(title, str)
                    else "",
                    "status": status_label,
                },
                idempotency_parts=(action.idempotency_key, "task_new"),
            )


_BUILTIN_TASK_SUBJECT = {
    "de": "Neue Aufgabe: Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}",
    "en": "New task: application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}',
}
_BUILTIN_TASK_BODY = {
    "de": "Hallo,\n\nder Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} hat einen "
    "Schritt erreicht, in dem du handeln kannst"
    "{% if status %} (Status: {{ status }}){% endif %}.\n",
    "en": "Hello,\n\nthe application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} reached a '
    "step where you can act"
    "{% if status %} (status: {{ status }}){% endif %}.\n",
}


def build_notify_dispatcher(pool: object) -> NotificationActionDispatcher:
    """Dispatcher aus dem (optionalen) arq-Pool bauen — App-Wiring (main.py)."""
    return NotificationActionDispatcher(
        get_sessionmaker(),
        mail_queue_from_pool(pool),  # type: ignore[arg-type]
        get_settings(),
    )

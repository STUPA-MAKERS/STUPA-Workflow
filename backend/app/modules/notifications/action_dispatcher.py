"""Flow action dispatcher for the `notify` and `taskNotify` actions.

The flow engine calls `ActionDispatcher.dispatch(actions)` after commit. This
dispatcher renders the mails and puts them on the mail queue. The worker sends
them. Every other action type only gets a log line here. This dispatcher does
not drop such an action and does not enqueue it.

`DispatchedAction.idempotency_key` is stable over the application, the status
event, the position and the type. A worker retry therefore never sends a
duplicate.
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
from app.modules.notifications.service import (
    NotificationService,
    resolve_application_lang,
)
from app.settings import Settings, get_settings

logger = logging.getLogger("app.notifications")


def _applicant_only(raw: object) -> bool:
    """Tell whether the recipients of a `notify` action are applicants only.

    `raw` is the recipient list as the flow stores it in JSONB. The service keeps
    only the dict entries of that list, so this function looks at the same set. An
    empty set, or one team recipient, gives False: those mails go out in the
    configured default language.
    """
    if not isinstance(raw, list):
        return False
    specs = [r for r in raw if isinstance(r, dict)]
    return bool(specs) and all(s.get("kind") == "applicant" for s in specs)


@dataclass(slots=True)
class NotificationActionDispatcher:
    """`ActionDispatcher` implementation for the notify actions.

    Every other action type only produces a log line.
    """

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
            title = (app_data or {}).get("title")
            context: dict[str, object] = {
                "applicationId": str(action.application_id),
                "applicationTitle": title.strip()
                if isinstance(title, str)
                else "",
            }
            raw_lang = action.params.get("lang")
            lang = str(raw_lang) if raw_lang else None
            # The action names no language and the mail goes to the applicant
            # alone: the applicant reads it in the language of their own
            # application. This must come before the status label below, because
            # a body in one language with a label in another is worse than a
            # consistent mail. A recipient list with a team member in it keeps
            # the default language, because one message serves them all.
            if lang is None and _applicant_only(action.params.get("recipients")):
                lang = await resolve_application_lang(
                    session,
                    application_id=action.application_id,
                    settings=self.settings,
                )
            # Default and status templates reference `{{ status }}`. Without a
            # value StrictUndefined makes the render fail.
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
        """Send a task mail because the application reached an actionable state.

        The dispatcher resolves the recipients at send time (task semantics).
        """
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
                    ).where(Application.id == action.application_id)
                )
            ).first()
            if row is None:
                return
            data, state_id = row
            state = (
                await session.scalar(select(State).where(State.id == state_id))
                if state_id is not None
                else None
            )
            # Send the task mail only when the new state is actionable: a vote
            # state, or a manual transition with requiresAction. For a
            # pass-through state or an end state "you can act" would be wrong.
            if not await state_actionable(session, state):
                return
            recipients = await actionable_principal_emails(
                session, application_id=action.application_id, state=state
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
    """Build the dispatcher from the optional arq pool (app wiring)."""
    return NotificationActionDispatcher(
        get_sessionmaker(),
        mail_queue_from_pool(pool),  # type: ignore[arg-type]
        get_settings(),
    )

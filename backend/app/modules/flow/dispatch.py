"""Action dispatch for the flow engine.

A fired transition produces worker actions. The engine dispatches them only after the
transaction commits, so they stay idempotent and retryable. `setEditLock` is not a
worker action. The edit lock comes from `edit_allowed` of the target state, and the
engine handles it inline.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

logger = logging.getLogger("app.flow.dispatch")

# Action types for the worker. The engine handles every other type inline.
WORKER_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "notify",
        "webhook",
        "addToNextSession",
        "assignBudget",
    }
)


@dataclass(frozen=True, slots=True)
class DispatchedAction:
    """A flow action to hand to the worker.

    `idempotency_key` is stable over the application, the status event, the position
    and the type. A retried worker run with the same key must not fire twice.
    """

    type: str
    application_id: UUID
    transition_id: UUID
    status_event_id: UUID
    idempotency_key: str
    params: dict[str, Any] = field(default_factory=dict)


def build_dispatched_actions(
    actions: Sequence[dict[str, Any]],
    *,
    application_id: UUID,
    transition_id: UUID,
    status_event_id: UUID,
) -> list[DispatchedAction]:
    """Map `transition.actions` (JSONB) to worker actions and skip `setEditLock`.

    `validate_action` already rejects unknown types at save time. The strict worker
    whitelist here keeps the inline-handled types out of the queue.
    """
    dispatched: list[DispatchedAction] = []
    for index, action in enumerate(actions):
        action_type = action.get("type")
        if action_type not in WORKER_ACTION_TYPES:
            continue
        params = {k: v for k, v in action.items() if k != "type"}
        dispatched.append(
            DispatchedAction(
                type=str(action_type),
                application_id=application_id,
                transition_id=transition_id,
                status_event_id=status_event_id,
                idempotency_key=f"{application_id}:{status_event_id}:{index}:{action_type}",
                params=params,
            )
        )
    return dispatched


def build_implicit_notifications(
    actions: Sequence[dict[str, Any]],
    *,
    application_id: UUID,
    transition_id: UUID,
    status_event_id: UUID,
) -> list[DispatchedAction]:
    """Build the implicit auto-mails for a status change, on top of the configured actions.

    The first mail is a `notify` to the applicant. It is skipped when the transition
    already carries an explicit applicant notify, so nobody gets the mail twice. The
    second mail is a `taskNotify` to everyone who can act on the new state. The
    recipients of that mail are resolved at send time.
    """
    applicant_covered = any(
        action.get("type") == "notify"
        and any(
            isinstance(r, dict) and r.get("kind") == "applicant"
            for r in action.get("recipients", [])
        )
        for action in actions
    )
    implicit: list[DispatchedAction] = []
    if not applicant_covered:
        implicit.append(
            DispatchedAction(
                type="notify",
                application_id=application_id,
                transition_id=transition_id,
                status_event_id=status_event_id,
                idempotency_key=f"{application_id}:{status_event_id}:auto:applicant",
                params={
                    "templateKey": "status_update",
                    "recipients": [{"kind": "applicant"}],
                },
            )
        )
    implicit.append(
        DispatchedAction(
            type="taskNotify",
            application_id=application_id,
            transition_id=transition_id,
            status_event_id=status_event_id,
            idempotency_key=f"{application_id}:{status_event_id}:auto:task",
        )
    )
    return implicit


@runtime_checkable
class ActionDispatcher(Protocol):
    """Worker dispatch interface."""

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None: ...


class NullActionDispatcher:
    """Default dispatcher: it logs each action without params or secrets, then drops it."""

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for action in actions:
            logger.info(
                "flow action dispatched (type=%s key=%s)",
                action.type,
                action.idempotency_key,
            )

"""Action dispatch for the flow engine.

Firing a transition produces worker actions that are dispatched only after the
transaction commits — idempotent and retryable. ``setEditLock`` is not a worker
action: the edit lock derives from the target state's ``edit_allowed`` and is
handled inline by the engine.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

logger = logging.getLogger("app.flow.dispatch")

# Action types handed to the worker; everything else is handled inline.
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

    ``idempotency_key`` is stable over (application, status event, position,
    type): a retried worker run with the same key must not double-fire."""

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
    """Map ``transition.actions`` (JSONB) to worker actions, skipping ``setEditLock``.

    Unknown types are already rejected at save time (``validate_action``); the
    strict worker whitelist here keeps inline-handled types from being enqueued."""
    dispatched: list[DispatchedAction] = []
    for index, action in enumerate(actions):
        action_type = action.get("type")
        if action_type not in WORKER_ACTION_TYPES:
            continue  # setEditLock etc. are inline/no-op, not for the worker.
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
    """Build implicit auto-mails per status change, on top of configured actions.

    ``notify`` to the applicant (skipped if the transition already carries an
    explicit applicant notify — no double send) plus ``taskNotify`` to everyone
    who can act on the new state (recipients resolved at send time)."""
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
    """Default dispatcher: logs actions (without params/secrets) and drops them."""

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for action in actions:
            logger.info(
                "flow action dispatched (type=%s key=%s)",
                action.type,
                action.idempotency_key,
            )

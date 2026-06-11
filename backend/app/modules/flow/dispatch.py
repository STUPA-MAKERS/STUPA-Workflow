"""Action-Dispatch der Flow-Engine (flows §9.3 Schritt 4).

Beim Feuern eines Übergangs entstehen **Worker-Actions** (``notify``, ``webhook``,
``exportPdf``, ``budgetReserve``, ``budgetBook``, ``openVote``, ``requeue``). Sie
werden **nach Commit** der Transaktion dispatcht — idempotent und retrybar.

Dies ist bewusst nur das **Interface** (T-14): die konkreten Handler liegen in den
Folge-Tasks (T-18 notify, T-19 webhook, T-20 exportPdf, T-17 budget, T-15 openVote/
requeue). Bis dahin ist :class:`NullActionDispatcher` der Default — er protokolliert
die Action (ohne Geheimnisse) und verwirft sie, statt eine noch fehlende Worker-
Funktion zu enqueuen.

``setEditLock`` ist **keine** Worker-Action: der Edit-Lock ergibt sich aus
``state.edit_allowed`` des Ziel-States (T-12 ``assert_editable``/409) und wird in der
Engine **inline** behandelt, nicht hier dispatcht.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

logger = logging.getLogger("app.flow.dispatch")

# Worker-Actions (an den Worker dispatcht). #28-Redesign: nur noch diese vier.
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
    """Eine an den Worker zu übergebende Flow-Action.

    ``idempotency_key`` ist stabil über (Antrag, Status-Event, Position, Typ): ein
    erneuter Worker-Lauf desselben Schlüssels darf **keinen** Doppeleffekt erzeugen
    (flows §9.3: idempotent/retrybar)."""

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
    """``transition.actions`` (JSONB) → Worker-Actions; ``setEditLock`` wird übersprungen.

    Unbekannte Typen sind durch das Speicher-Gate (``validate_action``, T-05)
    ausgeschlossen; hier wird zusätzlich strikt auf die Worker-Whitelist gefiltert,
    damit ein neuer (inline behandelter) Typ nicht versehentlich enqueued wird."""
    dispatched: list[DispatchedAction] = []
    for index, action in enumerate(actions):
        action_type = action.get("type")
        if action_type not in WORKER_ACTION_TYPES:
            continue  # setEditLock o. Ä. → inline/no-op, nicht an den Worker.
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
    """Implizite Auto-Mails je Statuswechsel (#4-3), zusätzlich zu den
    konfigurierten Flow-Actions:

    * ``notify`` an den Antragsteller (Status-Update) — entfällt, wenn der
      Übergang bereits eine explizite ``notify``-Action mit Applicant-Empfänger
      trägt (kein Doppelversand).
    * ``taskNotify`` an alle, die am neuen State handeln können (Task-Mail);
      der Handler löst die Empfänger zur Versandzeit auf.

    Abwahl einzelner Arten regelt die Empfänger-Filterung (#4-2)."""
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
    """Worker-Dispatch-Schnittstelle (konkrete Queue-Anbindung in T-18/19/20/17/15)."""

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None: ...


class NullActionDispatcher:
    """Default-Dispatcher: protokolliert Actions (ohne Params/Geheimnisse) und verwirft sie.

    Übergangslösung bis die ersten Worker-Handler existieren — der Contract (``fire``
    erzeugt Actions) ist damit vollständig, ohne fehlende Worker-Funktionen zu enqueuen."""

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for action in actions:
            logger.info(
                "flow action dispatched (type=%s key=%s)",
                action.type,
                action.idempotency_key,
            )

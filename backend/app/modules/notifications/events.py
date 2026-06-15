"""Stabile Event-Liste für Webhooks (api.md §6).

Single Source of Truth für die Event-Whitelist (Webhook-Abos, Schema-Validierung).
Neue Events hier ergänzen.
"""

from __future__ import annotations

# Reihenfolge = Dokumentations-/Anzeige-Reihenfolge (api.md §6).
EVENTS: tuple[str, ...] = (
    "application_created",
    "application_updated",
    "status_changed",
    "vote_opened",
    "vote_closed",
    "application_approved",
    "application_rejected",
    "comment_added",
    "budget_reserved",
    "budget_booked",
    "protocol_finalized",
    "deadline_approaching",
    "deadline_passed",
    "erasure_requested",
    "erasure_executed",
    "erasure_rejected",
)

EVENT_SET: frozenset[str] = frozenset(EVENTS)


def is_event(value: str) -> bool:
    """`True`, wenn `value` ein bekanntes Event ist (api.md §6)."""
    return value in EVENT_SET

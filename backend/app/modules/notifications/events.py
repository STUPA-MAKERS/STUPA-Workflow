"""Stable event list for webhooks.

This module is the single source of truth for the event whitelist. Webhook
subscriptions and schema validation read it. Add a new event here.
"""

from __future__ import annotations

# The tuple order is the documentation and display order.
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
    """Return `True` when `value` is a known event."""
    return value in EVENT_SET

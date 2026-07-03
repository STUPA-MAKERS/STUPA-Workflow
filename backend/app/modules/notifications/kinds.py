"""Catalog of configurable notification kinds.

A *kind* groups mails that belong together; the settings page
(``/account/notifications``) offers exactly these keys. Magic-link mails are
essential (login function) and deliberately NOT opt-out-able — they are
therefore not in the catalog.

On the sending side :meth:`NotificationService.filter_by_preference` filters
recipient addresses through this catalog; unknown kinds are never filtered
(fail-open on send, but 422 when saving unknown keys via the API).
"""

from __future__ import annotations

NOTIFICATION_KINDS: tuple[str, ...] = (
    # Own applications: status changes/updates (flow notify actions).
    "status_update",
    # New comments on applications that concern the user.
    "comment",
    # Application in a state where the own role can act.
    "task",
    # Reminder for stale open tasks.
    "task_reminder",
    # Meetings: invitation/agenda published.
    "meeting",
    # Votes opened/closed.
    "vote",
    # Own role assigned/revoked.
    "role_change",
    # Vote delegation received/revoked.
    "delegation",
    # Meeting protocol finalized.
    "protocol",
    # Deadline reminders on applications.
    "deadline",
    # GDPR erasure requests: received/executed/rejected.
    "privacy",
)

"""Catalog of configurable notification kinds.

A *kind* groups mails that belong together. The settings page
(`/account/notifications`) offers exactly these keys. Magic-link mails carry the
login function. A user must not switch them off, so they stay out of the
catalog.

On the sending side `NotificationService.filter_by_preference` filters the
recipient addresses through this catalog. An unknown kind is never filtered, so
a send fails open. The API still answers 422 when a caller saves an unknown key.
"""

from __future__ import annotations

NOTIFICATION_KINDS: tuple[str, ...] = (
    # Status changes and updates on own applications (flow notify actions).
    "status_update",
    # New comments on applications that concern the user.
    "comment",
    # An application reached a state where the own role can act.
    "task",
    # Reminder for an open task that did not move.
    "task_reminder",
    # A meeting invitation or an agenda was published.
    "meeting",
    # A vote was opened or closed.
    "vote",
    # An own role was assigned or revoked.
    "role_change",
    # A vote delegation was received or revoked.
    "delegation",
    # A meeting protocol was finalized.
    "protocol",
    # Deadline reminders on applications.
    "deadline",
    # GDPR erasure requests: received, executed or rejected.
    "privacy",
)

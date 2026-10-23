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
    # A vote delegation was received or revoked.
    "delegation",
    # A meeting protocol was finalized.
    "protocol",
    # Deadline reminders on applications.
    "deadline",
    # GDPR erasure requests: received, executed or rejected.
    "privacy",
    # A new ticket was reported (holders of ticket.manage). The confirmation to the
    # reporter (`ticket_received`) is not here, so nobody can switch it off.
    "ticket_created",
    # The reporter wrote on a ticket (the assignee, else every holder of ticket.manage).
    "ticket_message",
    # The team answered publicly on a ticket that the user reported.
    "ticket_answer",
    # A to-do was assigned to the user.
    "todo_assigned",
    # The user was mentioned in a comment of a to-do.
    "todo_mentioned",
    # Reminder the day before an assigned to-do is due.
    "todo_due",
    # The user was mentioned in a comment on an application or in a ticket note
    # (`comment_mentioned`, `ticket_mentioned`).
    "mention",
    # A poll of a Gremium of the user started (members with vote.cast).
    "poll_started",
    # Reminder 24 h before the end of a poll that the user has not answered.
    "poll_reminder",
)

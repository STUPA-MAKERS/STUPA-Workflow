"""Catalog of configurable notification kinds.

A *kind* groups mails that belong together. The settings page
(`/account/notifications`) offers exactly these keys. Magic-link mails carry the
login function. A user must not switch them off, so they stay out of the
catalog.

On the sending side `NotificationService.filter_by_preference` filters the
recipient addresses through this catalog. An unknown kind is never filtered, so
a send fails open. The API still answers 422 when a caller saves an unknown key.

The kinds:

- ``status_update``: status changes and updates on own applications (flow notify).
- ``comment``: new comments on applications that concern the user.
- ``task``: an application reached a state where the own role can act.
- ``task_reminder``: reminder for an open task that did not move.
- ``meeting``: a meeting invitation or an agenda was published.
- ``delegation``: a vote delegation was received or revoked.
- ``protocol``: a meeting protocol was finalized.
- ``privacy``: GDPR erasure requests (received, executed, rejected).
- ``ticket_created``: a new ticket was reported (holders of ``ticket.manage``). The
  confirmation to the reporter (``ticket_received``) is not here, so nobody can switch
  it off.
- ``ticket_message``: the reporter wrote on a ticket (the assignee, else every holder
  of ``ticket.manage``).
- ``ticket_answer``: the team answered publicly on a ticket that the user reported.
- ``todo_assigned``, ``todo_mentioned``, ``todo_due``: a to-do was assigned, the user
  was mentioned in a to-do comment, or an assigned to-do is due the next day.
- ``mention``: the user was mentioned in an application comment or a ticket note
  (``comment_mentioned``, ``ticket_mentioned``).
- ``poll_started``: a poll of a Gremium of the user started (members with
  ``vote.cast``).
- ``poll_reminder``: 24 h before the end of a poll that the user has not answered.
"""

from __future__ import annotations

NOTIFICATION_KINDS: tuple[str, ...] = (
    "status_update",
    "comment",
    "task",
    "task_reminder",
    "meeting",
    "delegation",
    "protocol",
    "privacy",
    "ticket_created",
    "ticket_message",
    "ticket_answer",
    "todo_assigned",
    "todo_mentioned",
    "todo_due",
    "mention",
    "poll_started",
    "poll_reminder",
)

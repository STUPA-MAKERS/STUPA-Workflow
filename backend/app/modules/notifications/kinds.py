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
- ``status_update_team``: a status change of an application that a flow ``notify``
  action sends to the team (every recipient kind except ``applicant``).
- ``poll_started``: a poll of a Gremium of the user started (members with
  ``vote.cast``).
- ``poll_reminder``: 24 h before the end of a poll that the user has not answered.
- ``appointment``: the user was invited to a Termin, or a Termin of the user moved,
  changed its place or was deleted (``appointment_invited``, ``appointment_changed``,
  ``appointment_cancelled``).
"""

from __future__ import annotations

NOTIFICATION_KINDS: tuple[str, ...] = (
    "status_update",
    "status_update_team",
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
    "appointment",
)

#: The kinds that are off until the person switches them on. They are the mails to
#: Gremium members about applications. One status change can mail a whole Gremium, so
#: a member gets them only after an explicit opt-in on the account page. The
#: preference table stores the deviation from this default: an ``enabled = true`` row
#: for one of these kinds, an ``enabled = false`` row for every other kind.
DEFAULT_OFF_KINDS: frozenset[str] = frozenset({"status_update_team", "task", "task_reminder"})


def kind_default(kind: str) -> bool:
    """Return the switch value of ``kind`` for a person who never changed it."""
    return kind not in DEFAULT_OFF_KINDS

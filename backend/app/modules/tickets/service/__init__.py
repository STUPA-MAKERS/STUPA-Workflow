"""Ticket service: report, list, detail, change, notes, anonymization.

The router resolves the Bereiche of the caller (``access.area_scope``) and passes
them as ``areas`` to every method of the team; None stands for every Bereich. A ticket
of a Bereich outside ``areas`` answers 404, and a list or a count leaves it out.
``create`` and the ``reporter_*`` methods take no scope. ``create_manual`` and
``reporter_follow_up`` do not commit; the router does. The service still decides who
may be the assignee (a person with the work right in the Bereich of the ticket) and
who may edit a note (its author).

The ``reporter_*`` methods are the view of the reporter account on its own tickets:
the report, the ``public`` notes and the status changes, plus its own messages. They
check the reporter themselves and answer 404 for any other ticket, so the routes are
no existence oracle. An anonymized ticket has no reporter any more.

The to-do coupling (``openTodoCount`` and ``completeTodos``) runs through
``TicketTodoHooks``. Without hooks the count is 0 and ``completeTodos`` changes no
card.

A team note can mention the persons with the work right in the Bereich of the ticket
(``mentions``, the set of ``assignees``); another id is 422 ``mention_not_member``. ``add_note`` and
``edit_note`` put the mentions that they added into ``added_mentions``, and the router
mails exactly those after the commit. A message of the reporter mentions nobody, its
edit keeps the stored mentions, and the view of the reporter never shows them.

Layout of the package:

``common``
    Constants, problem codes, types and small helpers.
``filters``
    The ``WHERE`` parts of the lists.
``rows``
    Pure serialization into the API schemas.
``base``
    Constructor, lookups, events and the sender check that every ops class shares.
``mail``, ``reads``, ``blocks``, ``create``, ``changes``, ``notes``, ``reporter``, ``anonymize``
    The ops classes, one concern each.
``service``
    The `TicketService` facade that combines them.

This package re-exports the public names, so ``from app.modules.tickets.service import
TicketService`` keeps working.
"""

from app.modules.tickets.models import TICKET_STATUSES
from app.modules.tickets.numbers import format_number
from app.modules.tickets.service.blocks import erase_sender_blocks, sender_blocks_of
from app.modules.tickets.service.common import (
    AssigneeFilter,
    SwallowedReport,
    TicketTodoHooks,
    normalize_email,
    principal_id_of,
)
from app.modules.tickets.service.reporter import (
    has_reported_tickets,
    reply_is_late,
    reporter_reads_file,
)
from app.modules.tickets.service.service import TicketService

__all__ = [
    "TICKET_STATUSES",
    "AssigneeFilter",
    "SwallowedReport",
    "TicketService",
    "TicketTodoHooks",
    "erase_sender_blocks",
    "format_number",
    "has_reported_tickets",
    "normalize_email",
    "principal_id_of",
    "reply_is_late",
    "reporter_reads_file",
    "sender_blocks_of",
]

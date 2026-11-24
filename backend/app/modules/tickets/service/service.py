"""Public facade of the ticket service.

`TicketService` combines the ops classes. The router and every other caller bind to
exactly this class:

* `create.CreateOps`: the report of the help menu and the ticket by hand
* `blocks.BlockOps`: the sender block and its match on a new report
* `reads.ReadOps`: list, counts, assignees and the detail view of the team
* `mail.MailOps`: mail answers, resend, mail source, Paperless filing
* `changes.ChangeOps`: status, assignee, Bereich, Kategorie and duplicate
* `notes.NoteOps`: the notes of the team
* `reporter.ReporterOps`: the view and the messages of the reporter account
* `anonymize.AnonymizeOps`: the anonymization of a ticket
"""

from __future__ import annotations

from app.modules.tickets.service.anonymize import AnonymizeOps
from app.modules.tickets.service.changes import ChangeOps
from app.modules.tickets.service.create import CreateOps
from app.modules.tickets.service.reporter import ReporterOps


class TicketService(CreateOps, ChangeOps, ReporterOps, AnonymizeOps):
    """Ticket operations bound to an ``AsyncSession``."""

"""The permission of the ticket module.

``ticket.manage`` gates every read and write of a ticket and of its attachments.
The report itself (``POST /tickets``) needs no permission.
"""

from __future__ import annotations

TICKET_MANAGE = "ticket.manage"

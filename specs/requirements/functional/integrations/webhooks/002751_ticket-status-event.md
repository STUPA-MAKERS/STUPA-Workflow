---
id: "002751"
title: A status change of a ticket is a webhook event
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_paperless_webhooks.py:test_each_status_change_is_an_event"
  - "backend/tests/unit/modules/tickets/test_ticket_webhooks.py:test_status_holds_both_statuses"
implementation:
  - backend/app/modules/tickets/webhook_fields.py
  - backend/app/modules/tickets/service/changes.py
  - backend/app/modules/webhooks/catalog.py
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/tickets
---

# A status change of a ticket is a webhook event

The event `ticket.status` must occur for each change of the status of a ticket, also for a
change without a person (002709, 002710). Its payload fields must include the number, the
title, the Bereich, the link, the old status and the new status. The event must carry the
Gremium of the Bereich (002749).

Reason: A different system follows the work on a ticket, for example to close its own case
when the ticket has the status `Erledigt`.

Test: A unit test sets the status of a ticket and expects one delivery with both statuses.

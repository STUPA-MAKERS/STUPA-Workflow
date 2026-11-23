---
id: "002705"
title: The admin page Hilfe & Tickets holds the Bereiche
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_delete_refuses_a_bereich_with_a_ticket"
  - "backend/tests/integration/modules/tickets/test_ticket_areas_api.py:test_an_admin_keeps_the_bereiche"
implementation:
  - backend/app/modules/tickets/areas.py
  - backend/app/modules/tickets/router.py
  - frontend/src/app/pages/admin/help-tickets/help-tickets.component.ts
  - frontend/src/app/pages/admin/help-tickets/ticket-area-dialog.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/admin/help-tickets
---

# The admin page Hilfe & Tickets holds the Bereiche

The admin page `Hilfe & Tickets` must list the Bereiche. An admin must be able to create a
Bereich, to change its name, its Gremium and its settings, and to delete a Bereich that holds no
ticket. The delete of a Bereich with a ticket must answer 409.

Reason: A Bereich with tickets holds a history that a delete would remove (000161).

Test: A unit test deletes a Bereich with one ticket and expects 409.

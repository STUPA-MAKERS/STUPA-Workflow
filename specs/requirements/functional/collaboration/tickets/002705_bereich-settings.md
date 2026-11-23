---
id: "002705"
title: The admin page Hilfe & Tickets holds the Bereiche
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
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

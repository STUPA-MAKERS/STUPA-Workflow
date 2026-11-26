---
id: "003042"
title: The detail of an Event changes the status in a dropdown
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-26
implementation:
  - frontend/src/app/pages/events/event-detail.component.html
  - frontend/src/app/pages/events/event-detail.component.ts
scope:
  - frontend/src/app/pages/events
---

# The detail of an Event changes the status in a dropdown

The detail of an Event must show the field "Status" above its fields. The field must be a
dropdown with every status of the list `event` in the order of the list, and it must show the
current status. A pick must save the status at once. The head must not show the status chip,
because the field shows the status. The detail must not have a status button, and its ⋮ menu
must not have a status. The ⋮ menu must have "Bearbeiten", "Folgeveranstaltung anlegen" and
"Löschen".

Reason: A dropdown shows the status and every other status at one place, and each change is
one pick. The Bestellungen do the same (002870).

Test: A frontend unit test opens an Event, reads the options of the field "Status" and the
actions, and picks a status.

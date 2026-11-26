---
id: "002870"
title: The detail of a Bestellung has its actions
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-26
implementation:
  - frontend/src/app/pages/orders/order-detail.component.ts
scope:
  - frontend/src/app/pages
---

# The detail of a Bestellung has its actions

For a person with `order.manage` the detail of a Bestellung (002936) must show the field
"Status" above its fields. The field must be a dropdown with every status of the list `order` in
the order of the list, and it must show the current status. A pick must save the status at once.
The head must not show the status chip for a person with `order.manage`, because the field shows
the status. A status of the phase `void` must ask first while the Bestellung has a booking. The
⋮ menu must have these actions in this order: "Rechnung verknüpfen", "Rechnung anlegen",
"Buchung anlegen", "Bearbeiten", "Löschen". The detail must not have a status button, and the
menu must not have a status. "Rechnung anlegen" and "Buchung anlegen" must show only for a
person with `budget.book`. "Löschen" must ask before it deletes.

Reason: A dropdown shows the status and every other status at one place, and each change is
one pick. An action that the person cannot use must not show.

Test: A frontend unit test opens the detail with and without `budget.book`, reads the actions
and the options of the field "Status", and picks a status.

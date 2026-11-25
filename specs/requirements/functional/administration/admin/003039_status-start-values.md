---
id: "003039"
title: The status lists start with the statuses of today
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/alembic/versions
scope:
  - backend/app/modules/statuses
  - backend/app/modules/orders
  - frontend/src/app/pages/admin
---

# The status lists start with the statuses of today

A migration must create the list of the Bestellungen with the statuses of 002853 and their keys:
`planned` (`Geplant`, open, start status), `ordered` (`Bestellt`, open, sets `Bestelldatum`),
`delivered` (`Geliefert`, done, sets `Lieferdatum`) and `cancelled` (`Storniert`, void). The
list of the Events must start with `planned` (`Geplant`, open, start status), `settled`
(`Abgerechnet`, done) and `cancelled` (`Abgesagt`, void). The stored Bestellungen must keep
their status.

Reason: After the update the platform must work as before, and the admin changes the lists
only when the work needs it.

Test: A migration test reads the four statuses of the Bestellungen with their phases and a
Bestellung that keeps its status.

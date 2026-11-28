---
id: "003104"
title: The pages Buchungen and Veranstaltungen fetch the pretix and Mollie data on demand
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/event_sales/sync.py
  - backend/app/modules/event_sales/router.py
  - frontend/src/app/shared/sales-sync.ts
scope:
  - backend/app/
  - frontend/src/app/
---

# The pages Buchungen and Veranstaltungen fetch the pretix and Mollie data on demand

The ⋮ menu of the page `Buchungen` and of the page `Veranstaltungen` must have the action
`Daten abrufen`. It must start at once the read of each integration that is on and configured
(pretix: 003085, 003086; Mollie: 003094, 003097, 003103), and must show the result when the run ends: the number of
new bookings and each failure with its cause. The action on `Buchungen` must need `budget.book`,
the action on `Veranstaltungen` must need the write right on an Event. The action of the detail
of an Event (003085) must also read the Mollie payments of that Event. A run must not start while
a run is in progress, and the API must then answer 409 `sync_running`. The action must show only
while at least one of the two integrations has its feature on (003081, 003093) and a
connection with an address and a token, and it must read only these integrations.

Reason: The worker reads on a timer. After a sale or a settlement, a person wants the bookings
now and must not wait for the next run.

Test: A backend unit test starts the run as a person with `budget.book` and reads a new booking,
gets 403 without the permission, and gets 409 for a second run during a run.

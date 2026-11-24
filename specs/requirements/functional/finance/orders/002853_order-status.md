---
id: "002853"
title: A Bestellung has four statuses for the goods
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
---

# A Bestellung has four statuses for the goods

The status of a Bestellung must be one of `planned` ("Geplant"), `ordered` ("Bestellt"),
`delivered` ("Geliefert") and `cancelled` ("Storniert"). A person must be able to set each
status from each other status. The status must not say if an invoice or a booking exists. A
change to "Bestellt" must set `orderedOn` to the current day and a change to "Geliefert" must
set `deliveredOn` to the current day, each only when the field is empty.

Reason: The status tells where the goods are. The invoice and the booking are their own
elements, and a status that repeats them can contradict them. A wrong delivery report must be
easy to take back, and a date that a person typed is more exact than the day of the click.

Test: A backend unit test sets each status from each other status, refuses a fifth value and
reads the dates after "Geliefert" on a Bestellung without dates and on one with a typed date.

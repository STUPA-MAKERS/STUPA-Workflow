---
id: "002853"
title: A Bestellung has four statuses
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
---

# A Bestellung has four statuses

The status of a Bestellung must be one of `planned` ("Geplant"), `ordered` ("Bestellt"),
`delivered` ("Geliefert") and `cancelled` ("Storniert"). A person must be able to set each
status from each other status. The status must not say if an invoice exists or if a booking
exists.

Reason: The status tells where the goods are. The invoice and the booking are their own
elements, and a status that repeats them can contradict them. A wrong delivery report must be
easy to take back.

Test: A backend unit test sets each status from each other status and refuses a fifth value.

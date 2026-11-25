---
id: "003097"
title: The Mollie money becomes suggested bookings
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The Mollie money becomes suggested bookings

When Mollie has payments of an Event, the action `Einnahme buchen` (003086) must suggest the sum
of the paid payments minus the refunds and the chargebacks as the income, and must also open the
form of a booking of the kind expense with the sum of the Mollie fees. A person must save each
booking, and the platform must not book money without the save of a person. The sales of pretix
must stay the suggestion for an Event without Mollie payments.

Reason: The income and the fees are two bookings in the budget. The money that arrived in Mollie
is the exact income, and the sales of pretix also hold payments outside Mollie, for example cash.

Test: A backend unit test reads the suggestion of an Event with Mollie payments and finds the
income and the fees, and finds no booking before a save.

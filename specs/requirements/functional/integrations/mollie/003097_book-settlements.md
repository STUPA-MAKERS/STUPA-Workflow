---
id: "003097"
title: Each Mollie settlement is booked automatically
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# Each Mollie settlement is booked automatically

While the switch `Einnahmen buchen` (003082) is on, for an Event with an
`Einnahmen-Kostenstelle` (003086), the worker must make two bookings for
each Mollie settlement that holds payments of the Event: one of the kind income with the sum of
the paid payments minus the refunds and the chargebacks, and one of the kind expense with the
sum of the Mollie fees. Both must have the date of the settlement, the Event as link and the
reference of the settlement in the text, and must name `Mollie` as their author in the audit
entry. Each settlement must be booked only once. For an Event with Mollie payments, 003086 must
not book the pretix sales. A booking that the platform cannot make must show on the admin page
`Mollie` with its cause.

Reason: The settlement is the money that arrives at the bank, so one booking per settlement
matches the bank statement. The income and the fees are two bookings in the budget.

Test: A backend unit test reads a fake settlement with two payments of an Event and finds one
income and one expense booking, and runs the cron again and finds no new booking.

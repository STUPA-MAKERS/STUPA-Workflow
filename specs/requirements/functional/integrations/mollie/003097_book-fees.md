---
id: "003097"
title: The Mollie fees are one booking per settlement
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The Mollie fees are one booking per settlement

The admin page `Mollie` must have the field `Gebühren-Kostenstelle`. While the switch
`Einnahmen buchen` (003082) is on and the field is set, the worker must make one booking of the
kind expense for each Mollie settlement with the sum of the Mollie fees of the settlement, the
date of the settlement and its reference in the text. The booking must link each Event that has
a payment in the settlement (003095). Each settlement must be booked only once. The booking must
name `Mollie` as its author in the audit entry. The income must stay the bookings of the orders
(003086). A booking that the platform cannot make must show on the admin page `Mollie` with its
cause.

Reason: Mollie takes its fees once per settlement, so one booking matches the bank statement.
The income per order and the fees per settlement are separate, so no sum is booked twice.

Test: A backend unit test reads a fake settlement with payments of two Events and finds one
expense booking with the fees linked to both Events, and runs the cron again and finds no new
booking.

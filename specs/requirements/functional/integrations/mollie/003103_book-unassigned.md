---
id: "003103"
title: A Mollie payment without an Event is booked without a link
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/event_sales/mollie_sync.py
scope:
  - backend/app/
  - frontend/src/app/
---

# A Mollie payment without an Event is booked without a link

The admin page `Mollie` must have the field `Kostenstelle für Zahlungen ohne Veranstaltung`.
While the switch `Einnahmen buchen` (003082) is on and the field is set, the worker must make
one booking of the kind income for each paid Mollie payment that belongs to no Event (003095):
with the sum of the payment, the date of the payment and the id of the payment in the text, and
without a link. A refund or a chargeback of such a payment must become one more booking that
takes the sum off the income. Each payment, refund and chargeback must be booked only once. The
booking must name `Mollie` as its author in the audit entry. The booking then shows in the list
`Buchungen` like each other booking, where a person can change it and link it.

Reason: Each euro that arrives in Mollie must reach the budget. A payment that the platform
cannot assign to an Event, for example from a shop without a link, is still income, and a person
assigns it by hand.

Test: A backend unit test reads a paid fake payment without pretix metadata and finds one income
booking on the cost centre of the field and without a link, and runs the cron again and finds no
new booking.

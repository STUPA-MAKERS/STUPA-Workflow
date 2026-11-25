---
id: "002878"
title: A booking can name a Bestellung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/budget/tree/expenses.py
  - backend/app/modules/orders/service.py
scope:
  - backend/app/modules/orders
  - backend/app/modules/budget
---

# A booking can name a Bestellung

An expense booking can name one Bestellung. One Bestellung can have many bookings. A person
must be able to set and to remove the Bestellung at the create and at the change of a booking.
The booking and the Bestellung must name the same Antrag or both must name none, else the
server must answer 422 `order_application_mismatch`. An income booking must not name a
Bestellung. The server must refuse the delete of a Bestellung with a booking with 409
`order_has_bookings`. When the delete of an Antrag deletes a Bestellung (002850), its bookings
must stay and must lose the reference.

Reason: The reference tells which purchase a payment paid. A purchase can have a deposit and a
rest. A booking from the time before the platform exists already, so the person adds the
Bestellung to it later. An income never belongs to an Antrag (F/finance/budget/000257). A
booked Bestellung is a record of the finances, so a person cancels it and does not delete it.

Test: A backend integration test books two times for one Bestellung, refuses a booking with a
different Antrag, sets and removes the Bestellung of a booking that exists and refuses the
delete of the Bestellung until both bookings are reverted.

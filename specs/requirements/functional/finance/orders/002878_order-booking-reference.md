---
id: "002878"
title: A booking can name a Bestellung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
---

# A booking can name a Bestellung

An expense booking can name one Bestellung. One Bestellung can have many bookings. The booking
must name the Antrag of the Bestellung, else the server must answer 422
`order_application_mismatch`. An income booking must not name a Bestellung. The delete of a
Bestellung must keep its bookings and must remove the reference.

Reason: The reference tells which purchase a payment paid. A purchase can have a deposit and a
rest. An income never belongs to an Antrag (F/finance/budget/000257).

Test: A backend integration test books two times for one Bestellung, refuses a booking with a
different Antrag and deletes the Bestellung without a loss of the bookings.

---
id: "002885"
title: The page Bestellungen filters like the bookings list
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - frontend/src/app/pages/orders/orders-page.component.ts
  - backend/app/modules/orders/listing.py
scope:
  - frontend/src/app/pages
  - backend/app/modules/orders
---

# The page Bestellungen filters like the bookings list

The page "Bestellungen" must filter by Haushaltsjahr, Kostenstelle, Gremium, kind and buyer, and
must search in the number, the Bezeichnung, the Händler and the Bestellnummer. The Kostenstelle,
the Haushaltsjahr and the Gremium of a Bestellung are those of its Antrag. A Bestellung without
an Antrag (003014) has the Kostenstellen and the Haushaltsjahre of the bookings that name it and
no Gremium: the filter by Gremium leaves it out, and without a booking the filters by
Kostenstelle and by Haushaltsjahr leave it out too.

Reason: The bookings list has the same filters, so a person finds a purchase the same way as a
payment. A Bestellung has no other responsible person than its buyer, so the buyer filter gives
a person the own purchases. A booking has a Kostenstelle and a Haushaltsjahr already, so a
Bestellung without an Antrag needs no field of its own for them.

Test: A backend integration test filters by Kostenstelle, by kind and by buyer and searches a
Bestellnummer. It finds a Bestellung without an Antrag by the Kostenstelle of its booking.

---
id: "002885"
title: The page Bestellungen filters like the bookings list
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages
  - backend/app/modules/orders
---

# The page Bestellungen filters like the bookings list

The page "Bestellungen" must filter by Haushaltsjahr, Kostenstelle, Gremium and kind, and must
search in the number, the Bezeichnung, the Händler and the Bestellnummer. The Kostenstelle and
the Haushaltsjahr of a Bestellung are those of its Antrag.

Reason: The bookings list has the same filters, so a person finds a purchase the same way as a
payment.

Test: A backend integration test filters by Kostenstelle and by kind and searches a
Bestellnummer.

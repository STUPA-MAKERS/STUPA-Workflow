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

The page "Bestellungen" must filter by Haushaltsjahr, Kostenstelle, Gremium, kind and buyer, and
must search in the number, the Bezeichnung, the Händler and the Bestellnummer. The Kostenstelle
and the Haushaltsjahr of a Bestellung are those of its Antrag.

Reason: The bookings list has the same filters, so a person finds a purchase the same way as a
payment. A Bestellung has no other responsible person than its buyer, so the buyer filter gives
a person the own purchases.

Test: A backend integration test filters by Kostenstelle, by kind and by buyer and searches a
Bestellnummer.

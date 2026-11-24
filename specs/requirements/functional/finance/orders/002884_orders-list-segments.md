---
id: "002884"
title: The page Bestellungen has three segments
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages
  - backend/app/modules/orders
---

# The page Bestellungen has three segments

The page "Bestellungen" must have these segments: "Offen" (status "Geplant" or "Bestellt"),
"Geliefert" (status "Geliefert" and the booked amount below the price) and "Erledigt" (status
"Storniert", or "Geliefert" and booked in full). The price is the real price, else the planned
price. A segment must not show a count.

Reason: The segments follow the work: wait for the delivery, book the delivery, done. A count at
a selector is not allowed on the platform.

Test: A backend unit test puts a delivered Bestellung with a part booking into "Geliefert" and
one with a full booking into "Erledigt".

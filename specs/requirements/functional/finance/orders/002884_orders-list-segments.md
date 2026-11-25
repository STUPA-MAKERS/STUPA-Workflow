---
id: "002884"
title: The page Bestellungen has three segments
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/pages/orders/orders-page.component.ts
  - backend/app/modules/orders/listing.py
scope:
  - frontend/src/app/pages
  - backend/app/modules/orders
---

# The page Bestellungen has three segments

The page "Bestellungen" must have these segments in this order: "Ohne Bestellung" (002934),
"Offen" (status "Geplant" or "Bestellt"), "Geliefert" and "Erledigt". The price of a Bestellung
is the real price, else the planned price. "Geliefert" must hold a Bestellung with the status
"Geliefert" whose booked amount is below its price, and one without a price and without a
booking. "Erledigt" must hold a Bestellung with the status "Storniert", one with the status
"Geliefert" that is booked in full, and one with the status "Geliefert" without a price and with
a booking. A segment must not show a count.

Reason: The segments follow the work: start the purchase, wait for the delivery, book the
delivery, done. A Bestellung without a price usually waits for its invoice, so it must stay
visible until a person books it. A count at a selector is not allowed on the platform.

Test: A backend unit test puts a delivered Bestellung with a part booking and one without a
price into "Geliefert", and one with a full booking and one without a price and with a booking
into "Erledigt".

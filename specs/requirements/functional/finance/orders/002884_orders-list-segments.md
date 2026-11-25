---
id: "002884"
title: The segments of the page Bestellungen follow the phases
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - frontend/src/app/pages/orders/orders-page.component.ts
  - backend/app/modules/orders/listing.py
scope:
  - frontend/src/app/pages
  - backend/app/modules/orders
---

# The segments of the page Bestellungen follow the phases

The page "Bestellungen" must have these segments in this order: "Ohne Bestellung" (002934),
"Offen" (a status of the phase `open`, 003036), "Geliefert" and "Erledigt". The price of a Bestellung
is the real price, else the planned price. "Geliefert" must hold a Bestellung in the phase
`done` whose booked amount is below its price, and one without a price and without a
booking. "Erledigt" must hold a Bestellung in the phase `void`, one in the phase `done`
that is booked in full, and one in the phase `done` without a price and with a booking. The code
must read the phase only, never a status key (003036). A segment must not show a count.

Reason: The segments follow the work: start the purchase, wait for the delivery, book the
delivery, done. A Bestellung without a price usually waits for its invoice, so it must stay
visible until a person books it. A count at a selector is not allowed on the platform.

Test: A backend unit test puts a Bestellung of the phase `done` with a part booking and one without a
price into "Geliefert", and one with a full booking and one without a price and with a booking
into "Erledigt".

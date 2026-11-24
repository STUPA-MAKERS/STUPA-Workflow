---
id: "002883"
title: The page Bestellungen lists the Bestellungen of all Anträge
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages
  - backend/app/modules/orders
---

# The page Bestellungen lists the Bestellungen of all Anträge

The finance pages must have the page "Bestellungen" at `/orders`, beside "Buchungen" and
"Rechnungen". The page must need `order.manage` or `budget.view`. It must
list the Bestellungen of the Anträge that the person reads, sorted by the newest change first.

Reason: The person who books needs the open purchases of all Anträge in one place, for example
what is delivered and not booked.

Test: A frontend unit test of the route guard refuses a person without the permissions. A
backend test lists only the Bestellungen of readable Anträge.

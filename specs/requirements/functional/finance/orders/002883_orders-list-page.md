---
id: "002883"
title: Bestellungen is a page of its own with a list and a detail
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - frontend/src/app/pages/orders/orders-page.component.ts
  - frontend/src/app/layout/nav.service.ts
  - backend/app/modules/orders/list_router.py
scope:
  - frontend/src/app/pages
  - backend/app/modules/orders
---

# Bestellungen is a page of its own with a list and a detail

The platform must have the page "Bestellungen" at `/orders` with its own entry in the main
navigation, beside "Buchungen" and "Rechnungen". The page must need `order.manage` or one of
`budget.view`, `budget.structure` and `budget.book`. It must be a list with a detail, like the
pages "Buchungen" and "Rechnungen": the list holds the Bestellungen that the person reads
(002863), sorted by the newest change first, and a row opens the detail of its Bestellung
beside the list (002936). The address `/orders?id=<id>` must open the page with this
Bestellung.

Reason: The person who buys and the person who books need the purchases of all Anträge in one
place, for example what is delivered and not booked. A place of its own makes the Bestellungen
easy to find, and a list with a detail is how the platform shows every other finance element.
The page opens for the same persons as "Buchungen" and "Rechnungen", so the three pages show
together.

Test: A frontend unit test of the route guard refuses a person without the permissions and
accepts each of the four. A frontend unit test opens `/orders?id=<id>` and reads the detail. A
backend test lists every Bestellung for a person with `budget.book`, and only the Bestellungen
of readable Anträge and those without an Antrag for a person with `order.manage` alone.

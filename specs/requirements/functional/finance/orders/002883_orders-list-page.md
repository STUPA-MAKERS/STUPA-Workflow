---
id: "002883"
title: Bestellungen is a page of its own with a list and a detail
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
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
navigation, beside "Buchungen" and "Rechnungen". The page must need `order.manage` or
`budget.view`. It must be a list with a detail, like the pages "Buchungen" and "Rechnungen": the
list holds the Bestellungen of the Anträge that the person reads, sorted by the newest change
first, and a row opens the detail of its Bestellung beside the list (002936). The address
`/orders?id=<id>` must open the page with this Bestellung.

Reason: The person who buys and the person who books need the purchases of all Anträge in one
place, for example what is delivered and not booked. A place of its own makes the Bestellungen
easy to find, and a list with a detail is how the platform shows every other finance element.

Test: A frontend unit test of the route guard refuses a person without the permissions. A
frontend unit test opens `/orders?id=<id>` and reads the detail. A backend test lists only the
Bestellungen of readable Anträge.

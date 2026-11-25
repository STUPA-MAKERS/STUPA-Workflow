---
id: "002877"
title: The invoice detail lists its Bestellungen
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/orders/router.py
  - frontend/src/app/pages/invoices/invoice-orders/invoice-orders.component.ts
scope:
  - frontend/src/app/pages/invoices
  - backend/app/modules/orders
  - backend/app/modules/budget
---

# The invoice detail lists its Bestellungen

The detail of an invoice must list the Bestellungen that name it, each with its number, its
Bezeichnung, its Antrag and its real price. It must show the sum of these real prices beside the
gross amount of the invoice. Each row must show its values, because the person who reads the
invoice reads every Bestellung (002863).

Reason: On an invoice for several purchases the person must see how much of the gross amount the
Bestellungen cover. A row "kein Zugriff" has no reader, now that one read right covers the
invoices and the Bestellungen.

Test: A frontend unit test renders an invoice with two Bestellungen and reads the rows and the
sum.

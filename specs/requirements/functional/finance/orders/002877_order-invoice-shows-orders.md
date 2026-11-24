---
id: "002877"
title: The invoice detail lists its Bestellungen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages/invoices
  - backend/app/modules/budget
---

# The invoice detail lists its Bestellungen

The detail of an invoice must list the Bestellungen that name it, each with its number, its
Bezeichnung, its Antrag and its real price. It must show the sum of these real prices beside the
gross amount of the invoice. A Bestellung of an Antrag that the reader does not read must show
as "Bestellung (kein Zugriff)".

Reason: On an invoice for several purchases the person must see how much of the gross amount the
Bestellungen cover.

Test: A frontend unit test renders an invoice with two Bestellungen and reads the rows and the
sum.

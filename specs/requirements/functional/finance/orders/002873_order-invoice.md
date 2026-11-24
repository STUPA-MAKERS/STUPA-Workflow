---
id: "002873"
title: A Bestellung has at most one invoice
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
  - backend/app/modules/budget
---

# A Bestellung has at most one invoice

A Bestellung must name at most one invoice. One invoice can belong to many Bestellungen, also of
different Anträge. The delete of an invoice must keep its Bestellungen and must remove the
reference. The set and the removal of the invoice of a Bestellung must need `order.manage` and
the read of the invoice.

Reason: One purchase at one Händler has one invoice, and the real price comes from it. A Händler
can put several purchases on one invoice. The delete follows the rule of the bookings
(F/finance/invoices/000260).

Test: A backend integration test gives two Bestellungen the same invoice, deletes the invoice
and reads both Bestellungen without an invoice.

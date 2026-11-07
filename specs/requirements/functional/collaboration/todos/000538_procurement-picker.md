---
id: "000538"
title: A Buchung and an invoice can name their Beschaffung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - frontend/src/app/pages/expenses
  - frontend/src/app/pages/invoices
---

# A Buchung and an invoice can name their Beschaffung

The form of a Buchung and the form of an invoice must have a `Beschaffung` picker. The picker
must create or delete the link of the Beschaffung card to the element. The picker must list
only open Beschaffungen on boards that the person can write.

Reason: The person who captures the invoice or the Buchung knows the purchase. The link must not need a second step on the board.

Test: A frontend unit test checks that the picker creates the card link.

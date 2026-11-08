---
id: "000552"
title: A card can link a cost centre
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - backend/app/modules/todos
  - backend/app/modules/budget
  - frontend/src/app/features/todos
  - frontend/src/app/pages/budget
---

# A card can link a cost centre

A card must be able to link a cost centre. A person must see the link only with the budget read
of the invoices and the bookings. The card of a cost centre must show its linked cards in a
section `Verknüpft` below the list of Anträge and bookings.

Reason: Work such as a Haushaltsplan item or an inventory belongs to a cost centre, not to one
Buchung.

Test: A backend unit test hides the link without budget read, and a frontend unit test shows it
on the cost centre card.

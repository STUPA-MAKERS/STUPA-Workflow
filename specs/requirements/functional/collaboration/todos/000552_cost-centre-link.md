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

A card must be able to link a cost centre. Each person who reads the card must see the name and
the path key of a linked cost centre. The cost centre page must keep its own read rule. The card
of a cost centre must show its linked cards in a section `Verknüpft` below the list of Anträge
and bookings.

Reason: Work such as a Haushaltsplan item or an inventory belongs to a cost centre, not to one
Buchung.

Test: A backend unit test shows the link to a reader of the card without budget read, and a
frontend unit test shows the card on the cost centre card.

---
id: "000533"
title: A Beschaffung is a card with procurement data
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# A Beschaffung is a card with procurement data

A card on a Gremium board or a team board can carry procurement data: the supplier and the
estimated amount in euro. Such a card is a Beschaffung. A card on a personal board must not
carry procurement data. The procurement data must be stored 1:1 to the card in
`todo_card_procurement`. The German UI calls it `Beschaffung`, the English UI calls it
`Procurement`.

Reason: A purchase goes through an Antrag, an invoice and a Buchung, often in different Kostenstellen. The card holds the steps, and the procurement data holds only the key data.

Test: A backend unit test sets procurement data on a card of each board kind.

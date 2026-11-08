---
id: "000555"
title: A checklist item becomes a card
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - frontend/src/app/features/todos
  - backend/app/modules/todos
---

# A checklist item becomes a card

A checklist item must have the action `Als Karte anlegen` (`Make card`). It must open the create
dialog on the board of the card with the text of the item as the title and a link to the card.
A created card must remove the item from the checklist.

Reason: An item can grow into its own work with a person and a due date.

Test: A frontend unit test makes a card from an item and checks the link and the removed item.

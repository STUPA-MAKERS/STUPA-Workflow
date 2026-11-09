---
id: "000555"
title: A checklist item becomes a card
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.ts
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.html
  - frontend/src/app/features/todos/new-dialog/todo-new-dialog.component.ts
scope:
  - frontend/src/app/features/todos
  - backend/app/modules/todos
---

# A checklist item becomes a card

A checklist item must have the action `Als Karte anlegen` (`Make card`). It must open the create
dialog on the board of the card with the text of the item as the title, the assignees of the card and a link to the card.
A created card must remove the item from the checklist. The card must also link to the created
card, so that `Verknüpft` (`Linked`) of each card shows the other.

Reason: An item can grow into its own work with a person and a due date.

Test: A frontend unit test makes a card from an item and checks the assignees, both links and the removed item.

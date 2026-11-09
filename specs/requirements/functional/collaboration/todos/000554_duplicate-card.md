---
id: "000554"
title: A card can be duplicated
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.ts
  - frontend/src/app/features/todos/new-dialog/todo-new-dialog.component.ts
  - backend/app/modules/todos/service.py
scope:
  - frontend/src/app/features/todos
  - backend/app/modules/todos
---

# A card can be duplicated

A card must have the action `Duplizieren` (`Duplicate`). It must open the create dialog with the
title, the description, the labels, the assignees, the due date, the links and the checklist of
the card. All checklist items must be open. The copy must not take the comments, the files of the
comments or the history. An Event must offer `Folgeveranstaltung anlegen` instead.

Reason: Many cards repeat with small changes, and spec 000142 gives a booking the same action.

Test: A frontend unit test duplicates a card and checks the copied fields and the open items.

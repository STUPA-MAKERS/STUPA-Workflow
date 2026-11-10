---
id: "000484"
title: Folgeveranstaltung anlegen copies the plan, not the facts
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/todos/service.py
  - backend/app/modules/todos/router.py
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.ts
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# Folgeveranstaltung anlegen copies the plan, not the facts

`Folgeveranstaltung anlegen` on an Event must create a new card in the first column of the same
board. The new card must get the title, the description, the labels, the place, the series and
the checklist with all items open. The new card must not get links, assignees, comments,
dates or the history.

Reason: The plan repeats each time. The Anträge, Buchungen and decisions belong to one edition
only.

Test: A backend unit test checks the fields of the new card.

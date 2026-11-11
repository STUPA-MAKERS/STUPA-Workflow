---
id: "000488"
title: A to-do becomes an Event only once
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/todos/service.py
  - frontend/src/app/features/todos/new-dialog/todo-new-dialog.component.ts
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.ts
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# A to-do becomes an Event only once

The dialog for a new card must have the switch `To-Do | Veranstaltung`. The menu of a to-do
card must have `Zur Veranstaltung umwandeln`. This action must ask for a confirmation with the
text that it cannot be undone. An Event must not become a to-do again. The menu of an Event
must have `Folgeveranstaltung anlegen` and no action that removes the event data.

Reason: The links, totals and decisions of an Event belong to it. Without the event data they
lose their meaning.

Test: A backend unit test gets 409 when it removes the event data of an Event.

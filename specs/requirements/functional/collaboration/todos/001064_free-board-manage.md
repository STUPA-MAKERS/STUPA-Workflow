---
id: "001064"
title: Members with Verwalten and admins manage a free board
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_the_last_manager_stays"
  - "frontend/src/app/pages/todos/board-settings/todo-board-settings.component.spec.ts:TodoBoardSettingsComponent"
implementation:
  - backend/app/modules/todos/service.py
  - frontend/src/app/pages/todos/board-settings/todo-board-settings.component.ts
  - frontend/src/app/pages/todos/board-entries/todo-board-entries.component.ts
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# Members with Verwalten and admins manage a free board

Only the persons with the role `Verwalten` on a free board and the admins must be able to change
its name, columns, labels, settings and member entries. The settings sheet of the board must have
the section `Mitglieder` (`Members`) with the member entries and their roles. The last entry with
`Verwalten` must not be removed or lowered, else the request must answer 409 `last_manager`.

Reason: Each free board needs a person who can maintain it, also when its creator leaves.

Test: A backend test removes the last entry with `Verwalten` and gets 409.

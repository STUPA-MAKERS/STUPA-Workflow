---
id: "001068"
title: A manager archives a free board and only an admin deletes it
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_archive_restore_and_delete"
  - "frontend/src/app/pages/todos/archived-boards/todo-archived-boards.component.spec.ts:TodoArchivedBoardsComponent"
implementation:
  - backend/app/modules/todos/service/boards.py
  - backend/app/modules/todos/router.py
  - frontend/src/app/pages/todos/archived-boards/todo-archived-boards.component.ts
  - frontend/src/app/pages/todos/board-settings/todo-board-settings.component.ts
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# A manager archives a free board and only an admin deletes it

A person with `Verwalten` must be able to archive a free board. An archived board must not show
in the board picker, in `Alle`, in `Meine To-Dos` or in the search, and must be read-only. A
person with `Verwalten` must be able to restore it from the list of archived boards. Only an admin
must be able to delete a free board, after an archive, and the delete must remove its cards with
their comments, files and links.

Reason: An archive keeps the work for later reference, and a delete cannot be undone.

Test: A backend test archives a board, writes a card and gets 409 `board_archived`, then deletes
the board as a manager and gets 403.

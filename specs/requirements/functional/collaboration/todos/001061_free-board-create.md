---
id: "001061"
title: Admins and holders of todo.create_board create a free board
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# Admins and holders of todo.create_board create a free board

Only an admin and a holder of the global permission `todo.create_board` (`Boards anlegen`) must
be able to create a free board. A create without the right must answer 403
`board_create_required`. The creator must become a member of the new board with the role
`Verwalten`. The board picker of the Boards tab must have the action `Neues Board` (`New board`)
for these persons only. The migration must give the permission to the role `admin`.

Reason: A free board is visible to many persons, so not each person may create one.

Test: A backend test creates a board with and without the permission, and a frontend test
shows the action only with the permission.

---
id: "001066"
title: todo.all and todo.read_all reach free boards
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_a_global_key_reads_a_free_board"
implementation:
  - backend/app/modules/todos/access.py
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# todo.all and todo.read_all reach free boards

The global permissions `todo.all` and `todo.read_all` must reach every free board as they reach
every board of a Gremium: `todo.all` reads and writes the cards, `todo.read_all` only reads them.
Neither must configure a free board, and neither must make a person a member.

Reason: The platform admins must see all shared work. A free board is shared work like a board of
a Gremium.

Test: A backend test reads a free board with `todo.read_all` as a non-member and writes it with
`todo.all`.

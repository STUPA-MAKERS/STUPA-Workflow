---
id: "001060"
title: A free board belongs to no single Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_only_the_permission_creates_a_free_board"
implementation:
  - backend/app/modules/todos/models.py
  - backend/app/modules/todos/service/boards.py
  - backend/migrations/versions/c6010961aa02_todo_free_boards.py
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# A free board belongs to no single Gremium

There must be free boards beside the boards of a Gremium, the personal boards and the team
boards. A free board must have a name and a list of members. A member entry must be either a
Gremium or one person, and a free board can have any number of both. A free board can have no
Gremium at all.

Reason: Work that spans several Gremien, or a project group of single persons, has no board of
its own today.

Test: A backend test creates a free board with two Gremien and one person and reads it as a
member of each Gremium and as the person.

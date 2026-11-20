---
id: "001077"
title: A board of a Gremium takes more Gremien and persons
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_a_gremium_board_takes_entries_and_every_member_edits"
  - "frontend/src/app/pages/todos/board-settings/todo-board-settings.component.spec.ts:TodoBoardSettingsComponent"
implementation:
  - backend/app/modules/todos/service.py
  - frontend/src/app/pages/todos/board-settings/todo-board-settings.component.ts
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# A board of a Gremium takes more Gremien and persons

A board of a Gremium must take more member entries like a free board (001060, 001062): any
number of other Gremien and persons, each with the role `Lesen`, `Bearbeiten` or `Verwalten`.
Its own Gremium must be a fixed entry that cannot be removed or changed. The managers of the board
(001078) and the admins must be able to add, change and remove the other entries in the section
`Mitglieder` of the board settings, with the picker of ui-kit:001074.

Reason: The work of a Gremium often needs a person or another Gremium that is not a member of it.

Test: A backend test adds a person with `Bearbeiten` to a Gremium board, writes a card as that
person, and removes the own Gremium entry with 409 `own_gremium_entry`.

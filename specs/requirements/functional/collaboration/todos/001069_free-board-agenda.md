---
id: "001069"
title: A card of a free board goes on the agenda of each of its Gremien
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_a_card_of_a_free_board_goes_on_the_agenda_of_its_gremien"
implementation:
  - backend/app/modules/todos/access.py
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.ts
  - frontend/src/app/features/todos/agenda-dialog/todo-agenda-dialog.component.ts
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/livevote
---

# A card of a free board goes on the agenda of each of its Gremien

The action `Auf Tagesordnung setzen` (000553) must also show on a card of a free board. It must
offer only the planned meetings of the Gremien that have access to the board through a member
entry, with any role, and whose agenda the person can edit, grouped by Gremium, the next meeting first. A free board without such a
Gremium must not show the action. A card must still be on at most one agenda (000326).

Reason: A board of several Gremien prepares work for the meetings of each of them.

Test: A backend test puts a card of a free board on a meeting of one of its Gremien and gets 422
`todo_wrong_board` for a Gremium that is not on the board.

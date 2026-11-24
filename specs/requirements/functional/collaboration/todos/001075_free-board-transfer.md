---
id: "001075"
title: A card moves between a free board and other shared boards
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_a_card_moves_between_a_free_board_and_a_gremium_board"
implementation:
  - backend/app/modules/todos/service/cards.py
  - backend/app/modules/todos/service/ranks.py
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# A card moves between a free board and other shared boards

A free board must be a shared board for the transfer rules (000321, 000322): a card can move
between a free board and a board of a Gremium, a team board or another free board, and must not
move from a free board to a personal board.

Reason: Work moves from a project group to a Gremium and back.

Test: A backend test moves a card from a free board to a Gremium board and back.

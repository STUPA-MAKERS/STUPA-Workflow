---
id: "003130"
title: The board picker calls the group of the team boards Teams
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "frontend/src/app/pages/todos/board-picker/todo-board-picker.component.spec.ts:TodoBoardPickerComponent"
implementation:
  - frontend/src/app/pages/todos/board-picker/todo-board-picker.component.ts
scope:
  - frontend/src/app/pages/todos
---

# The board picker calls the group of the team boards Teams

The board picker of the Boards tab must show the boards of the kind `team` (003067: the board
of each Gremium and of each other team) under the group heading `Teams` (`Teams`), not
`Gremien`. Each of these boards, and the board chip while one of them is open, must show the
icon of the tab Teams (`network`), not the icon of a Gremium (`landmark`). The order of the
groups (001067) and the groups `Persönlich` and `Weitere Boards` must not change.

Reason: Since 003067 a board belongs to a team, not to a Gremium, and the tab is called Teams.
The old heading and icon name an owner that the board no longer has.

Test: A frontend test shows the board of a team under the heading `Teams` with the icon
`network`.

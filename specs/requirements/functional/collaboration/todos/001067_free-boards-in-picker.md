---
id: "001067"
title: Free boards show in the board picker after the boards of the Gremien
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/pages/todos/board-picker/todo-board-picker.component.spec.ts:TodoBoardPickerComponent"
implementation:
  - frontend/src/app/pages/todos/board-picker/todo-board-picker.component.ts
  - backend/app/modules/todos/service/boards.py
  - backend/app/modules/todos/service/common.py
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# Free boards show in the board picker after the boards of the Gremien

The board picker of the Boards tab must show the free boards that the person reads in their own
group `Weitere Boards` (`More boards`) after the boards of the Gremien, sorted by name. The
meta-board `Alle` and `Meine To-Dos` must include the free boards. The route of a free board must
be `/todos/<boardId>` like every other board. The group heading must not show a count.

Reason: A free board must be found where every other board is found.

Test: A frontend test shows a free board in its group after the Gremium boards.

---
id: "001967"
title: The menu of a board column stands in its top right corner
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/pages/todos/board-view/todo-board-view.component.scss
scope:
  - frontend/src/app/pages/todos
---

# The menu of a board column stands in its top right corner

On every board, also on "Meine To-Dos", the ⋮ menu of a column must stand at the end of the head
of the column, in its top right corner. The title stands at the start. The tag of the done column
stands directly before the menu.

Reason: The menu stood directly after the title, so its place moved with the length of the name,
and the menus of the columns did not line up.

Test: A screenshot of a board on a wide screen shows each ⋮ menu at the right edge of its column.

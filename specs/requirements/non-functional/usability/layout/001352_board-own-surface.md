---
id: "001352"
title: Each board lies on a surface of its own
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/todos/todos.component.scss
  - frontend/src/app/pages/todos/board-view/todo-board-view.component.scss
  - frontend/src/app/pages/todos/board-rows/todo-board-rows.component.scss
scope:
  - frontend/src/app/pages/todos
---

# Each board lies on a surface of its own

On a wide screen, each board on the board page must lie on a surface of its own with rounded
corners: the board at the top of the page and each board row below it. The columns must scroll
sideways inside that surface and must cut hard at its edge (spec 000193). The surface has the
colour `--color-surface-1`. In the dark theme, a column has the colour `--color-surface-2`, so
that it stands out from the surface.

In the very high contrast mode (000605), the surface must have a white edge. The body of the
board page must then have no frame of its own.

Reason: A cut must look intended. Columns that end at the visible edge of a surface do; columns
that end at the gutter of the page do not.

Test: Style review of the board page in the light theme, the dark theme and the very high
contrast mode, with the board scrolled sideways.

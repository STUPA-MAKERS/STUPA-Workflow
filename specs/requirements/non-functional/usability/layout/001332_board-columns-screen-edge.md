---
id: "001332"
title: Board columns cut at the screen edge and stand out from the page
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/todos/todos.component.scss
  - frontend/src/app/pages/todos/board-view/todo-board-view.component.scss
  - frontend/src/app/pages/todos/board-rows/todo-board-rows.component.scss
  - frontend/src/app/features/todos/card-tile/todo-card-tile.component.scss
scope:
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# Board columns cut at the screen edge and stand out from the page

On a wide screen, the columns of a board must scroll sideways up to the screen edge and up to the
navigation rail. They must not cut at the gutter of the page (spec 000193). This applies to the
board at the top of the page and to each board row below it.

A board column must have the surface colour `--color-surface-3`. In the dark theme, a card in a
column must have the colour `--color-surface-4`, one step lighter than the column.

In the very high contrast mode (000605), the body of the board page must not have a frame of its
own, because the frame would touch the line of the rail. Each column keeps its white edge.

Reason: A column that ends before the screen edge looks cut off for no reason. A column with
the colour of the page does not read as a surface in the dark theme.

Test: Style review of the board page in the light theme, the dark theme and the very high
contrast mode, with the board scrolled sideways.

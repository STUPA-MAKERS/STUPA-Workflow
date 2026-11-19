---
id: "001380"
title: The move sheet lists the columns as the select sheet does
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/todos/move-sheet/todo-move-sheet.component.spec.ts:TodoMoveSheetComponent"
implementation:
  - frontend/src/app/features/todos/move-sheet/todo-move-sheet.component.html
  - frontend/src/app/features/todos/move-sheet/todo-move-sheet.component.scss
scope:
  - frontend/src/app/features/todos/move-sheet
---

# The move sheet lists the columns as the select sheet does

The column list of the "Verschieben" sheet (000148) must show the rows of the phone sheet of a
select: a row group of tiles on surface 3, no radio circle, and a check mark after the name of
the chosen column. "In anderes Board verschieben" must be a row of its own row group below
the columns, with a chevron at the end and no separator line.

Reason: The sheet was the only list in the app with full-width rows, radio circles and a
separator line, so it did not read as the choice lists of the other sheets.

Test: `todo-move-sheet.component.spec.ts` checks the radio rows, the check mark and the row of
the other board.

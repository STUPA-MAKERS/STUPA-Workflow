---
id: "000607"
title: An agenda row shows no drag handle
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.spec.ts:AgendaPaneComponent"
implementation:
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.html
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.scss
scope:
  - frontend/src/app/features/meetings
---

# An agenda row shows no drag handle

An agenda row must not show a drag handle (the six-dot icon), also not on hover or focus. A
user who can change the agenda must still move a TOP by a drag on the whole row and by the
move entries of the row menu.

Reason: The handle is visual noise next to the TOP number. The whole row is the drag target,
so the handle adds no function.

Test: The agenda pane test finds no `.ap__grip` element while every row can be dragged.

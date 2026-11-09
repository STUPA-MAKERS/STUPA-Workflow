---
id: "000575"
title: The details of a card cut at the lower screen edge
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.scss
scope:
  - frontend/src/app/features/todos/card-detail
---

# The details of a card cut at the lower screen edge

On a wider screen, the details column of a to-do card in the side sheet beside the board must
run to the lower edge of the sheet. Its content must cut hard at that edge and must not fade
there. The upper end of the column still fades (000193).

Reason: The lower edge of the sheet is the edge of the screen, which is a real line.

Test: Screenshot of an open card with a long details column on a desktop width.

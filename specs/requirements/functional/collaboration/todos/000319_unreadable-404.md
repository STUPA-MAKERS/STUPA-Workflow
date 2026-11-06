---
id: "000319"
title: An unreadable board is not found
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# An unreadable board is not found

A board, card or sub-resource that the caller cannot read must answer 404, never 403. A write
on a readable board without write right must answer 403 `todo_write_required`.

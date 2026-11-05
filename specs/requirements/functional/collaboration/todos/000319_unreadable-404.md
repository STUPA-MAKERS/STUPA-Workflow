---
id: "000319"
title: An unreadable board is not found
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# An unreadable board is not found

A board, card or sub-resource that the caller cannot read answers 404, never 403. A write on
a readable board without write right answers 403 `todo_write_required`.

---
id: "000320"
title: Only members are assigned or mentioned
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# Only members are assigned or mentioned

An assignee or a mention must be a member of the board. A holder of `todo.all` or
`todo.read_all` is not a member through that key.

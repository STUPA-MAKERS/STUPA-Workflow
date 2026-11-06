---
id: "000318"
title: Board rights depend on the board kind
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# Board rights depend on the board kind

A Gremium board must need `todo.write` to write and `todo.configure` to configure. A personal
board must be only for its owner, without an admin bypass. A team board must be for the holders
of its permission.

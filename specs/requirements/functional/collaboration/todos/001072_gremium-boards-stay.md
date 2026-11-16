---
id: "001072"
title: The board of a Gremium stays its own kind
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# The board of a Gremium stays its own kind

Each Gremium must keep exactly one board of the kind `gremium`, with the rights of 001078. A free
board must be a new kind `free` with its own member entries. A board of a Gremium must not turn
into a free board, and a free board must not turn into a board of a Gremium.

Reason: The board of a Gremium is created and deleted with the Gremium, and its own Gremium is a
fixed member. A free board has no such owner.

Test: A backend test creates a Gremium and finds its board of the kind `gremium`.

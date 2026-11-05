---
id: "000324"
title: Boards update live
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# Boards update live

A change of a board sends a ping over the socket. The client then reads the change through
REST, so every read rule stays in force.

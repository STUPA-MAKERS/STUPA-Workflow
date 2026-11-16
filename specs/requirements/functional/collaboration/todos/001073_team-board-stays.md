---
id: "001073"
title: The team board Plattform stays a team board
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/todos/models.py
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# The team board Plattform stays a team board

The team board `Plattform` must stay a team board for the holders of `ticket.manage` (000147).
It must not become a free board.

Reason: The tickets, the routines and the board sync of the platform work use the board and its
permission.

Test: A backend test reads the board `Plattform` as a holder of `ticket.manage`.

---
id: "000147"
title: Boards per Gremium, per person and per team
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/todos/boards.py
  - backend/app/modules/todos/access.py
  - backend/app/modules/todos/models.py
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# Boards per Gremium, per person and per team

There must be boards per Gremium, one personal board per person and the team board "Plattform"
for `ticket.manage`.

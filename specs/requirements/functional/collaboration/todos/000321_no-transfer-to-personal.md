---
id: "000321"
title: A shared card does not move to a personal board
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

# A shared card does not move to a personal board

A card on a Gremium or team board must not move to a personal board, else the request must
answer 403 `transfer_to_personal`.

Reason: The comments, files and links would leave the reach of the other members.

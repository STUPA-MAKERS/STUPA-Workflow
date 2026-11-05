---
id: "000321"
title: A shared card does not move to a personal board
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# A shared card does not move to a personal board

A card on a Gremium or team board cannot move to a personal board, else 403
`transfer_to_personal`.

Reason: The comments, files and links would leave the reach of the other members.

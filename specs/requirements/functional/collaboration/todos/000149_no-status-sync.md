---
id: "000149"
title: No status sync between ticket and card
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/tickets
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/tickets
---

# No status sync between ticket and card

A ticket and its card must not sync their status automatically. When a ticket is done, the
platform must ask about the card.

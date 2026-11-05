---
id: "000149"
title: No status sync between ticket and card
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/tickets
---

# No status sync between ticket and card

A ticket and its card do not sync their status automatically. When a ticket is done, the
platform asks about the card.

---
id: "000447"
title: Pool seats need only a live meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/pool_seat.py
scope:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# Pool seats need only a live meeting

A pool seat must need only a live meeting, not a delegation before the start.

---
id: "000446"
title: The member frees the pool seat
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/pool_seat.py
  - backend/app/modules/meetings/attendance_service.py
scope:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# The member frees the pool seat

A check-in or an own ballot of the member must free the seat of the pool substitute. A ballot
already cast for the member must stay.

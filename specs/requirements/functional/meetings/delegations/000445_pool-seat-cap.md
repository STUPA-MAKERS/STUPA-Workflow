---
id: "000445"
title: Pool seats never exceed the member seats
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/pool_seat.py
  - backend/app/modules/voting/service.py
scope:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# Pool seats never exceed the member seats

Each pool substitute must take one seat, and each member seat must get one ballot. Members and
substitutes must never exceed the seats.

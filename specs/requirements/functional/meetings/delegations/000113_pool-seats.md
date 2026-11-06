---
id: "000113"
title: A pool substitute takes a free seat
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

# A pool substitute takes a free seat

A pool substitute must be able to vote for a member who is not checked in, without an
announcement and without a delegation. The substitute can be a non-member.

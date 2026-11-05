---
id: "000113"
title: A pool substitute takes a free seat
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# A pool substitute takes a free seat

A pool substitute votes for a member who is not checked in, without an announcement and
without a delegation. The substitute can be a non-member. Each substitute takes one seat, and
each member seat gets one ballot, so members and substitutes never exceed the seats. A
check-in or an own ballot of the member frees the seat. A ballot already cast for the member
stays. Pool seats need only a live meeting.

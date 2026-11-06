---
id: "000366"
title: A delegation has a deadline
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations
scope:
  - backend/app/modules/delegations
---

# A delegation has a deadline

A normal delegation must be possible until `delegation_lead_minutes` before the meeting start.
A pool delegation must be possible until the start. Both must need a planned meeting. The lead
entry of a pool substitute (000420) is the exception: it needs a live meeting.

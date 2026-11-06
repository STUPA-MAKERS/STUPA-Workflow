---
id: "000103"
title: Lead-set attendance wins
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/attendance_service.py
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# Lead-set attendance wins

An attendance status that the meeting lead sets must win. The member must not be able to change
it. An own ballot must mark the voter as present.

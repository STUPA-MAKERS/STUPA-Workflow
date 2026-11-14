---
id: "000922"
title: A member can give an excuse after the meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/meetings
  - frontend/src/app/features/meetings
  - frontend/src/app/features/gremien
---

# A member can give an excuse after the meeting

A member must be able to change the own status from `absent` to `excused` until
`lateExcuseDays` days after the close of the meeting (000917). The change must need a note.

Reason: The Geschäftsordnung lets a member give the excuse within one week with the cause.

Test: An integration test that sets the status after the period and gets 409.

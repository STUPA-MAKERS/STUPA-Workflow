---
id: "000922"
title: A member can give an excuse after the meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/meetings/attendance_service.py
  - frontend/src/app/features/meetings/late-excuse-dialog/late-excuse-dialog.component.ts
scope:
  - backend/app/modules/meetings
  - frontend/src/app/features/meetings
  - frontend/src/app/features/gremien
---

# A member can give an excuse after the meeting

A member must be able to change the own status from `absent` to `excused` until
`lateExcuseDays` days after the close of the meeting (000917). The period must end with the
end of its last day in local time. The change must need a note.

Reason: The Geschäftsordnung lets a member give the excuse within one week with the cause.

Test: An integration test that sets the status after the period and gets 409.

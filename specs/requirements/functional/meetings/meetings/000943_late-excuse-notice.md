---
id: "000943"
title: A late excuse sends a mail to the lead
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/meetings/absence.py
  - backend/app/modules/notifications
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - backend/app/modules/notifications
---

# A late excuse sends a mail to the lead

When a member hands in a late excuse (000922), the platform must send the mail `late_excuse`
to the persons with `session.manage` in the Gremium. The mail must name the member, the
meeting and the reason. The excuse must apply at once and must not wait for an answer.

Reason: A late excuse changes the count of the unexcused absences (000920). The Vorsitz must
know of this change.

Test: An integration test that hands in a late excuse and reads the queued mail.

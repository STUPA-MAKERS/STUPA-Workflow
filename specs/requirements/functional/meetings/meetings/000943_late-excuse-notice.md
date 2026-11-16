---
id: "000943"
title: A late excuse sends a mail to the lead
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/livevote/test_meeting_periods.py:test_late_excuse_mails_the_managers_with_the_reason"
  - "backend/tests/unit/modules/livevote/test_meeting_periods_unit.py:test_late_excuse_route_passes_the_reason"
implementation:
  - backend/app/modules/livevote/mails.py
  - backend/app/modules/livevote/router.py
  - backend/app/modules/notifications/texts/meetings.py
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

---
id: "001711"
title: A draft without a change for 7 days gets one reminder mail
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - backend/app/modules/notifications
  - backend/worker
---

# A draft without a change for 7 days gets one reminder mail

When a draft (001710) has had no change for 7 days, the worker must send the mail
`draft_reminder` to the applicant. The mail must link to the draft. Each draft must get this mail
at most once. The applicant must be able to switch the mail off in the notification settings.

Reason: A draft that nobody submits is an Antrag that nobody decides.

Test: A backend unit test runs the cron for a draft of 6 days, of 7 days, and of 7 days with a mail already sent.

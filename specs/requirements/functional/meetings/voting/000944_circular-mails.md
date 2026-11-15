---
id: "000944"
title: A circular vote sends a mail at its open and before its end
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/voting/circular.py
  - backend/app/modules/notifications
scope:
  - backend/app/modules/voting
  - backend/app/modules/notifications
  - backend/worker
---

# A circular vote sends a mail at its open and before its end

When a circular vote (000914) opens, the platform must send the mail `circular_open` to each
eligible member. The mail must show the question, the end of the cast window and a link to the
vote. One day before the end, the platform must send the mail `circular_reminder` to each
eligible member that has cast no ballot. The reminder must go out one time only.

Reason: A circular vote needs the majority of the members (000894), so a ballot that is not
cast counts as a no. A member must know that the vote runs.

Test: An integration test that opens a circular vote and reads the queued mails, and a test of
the cron that sends the reminder only to the member without a ballot.

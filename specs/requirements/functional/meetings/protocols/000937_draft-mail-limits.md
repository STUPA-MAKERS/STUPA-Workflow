---
id: "000937"
title: The draft mail waits for the end of the meeting and asks before a repeat
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/protocol/test_protocol_draft_and_approval.py:test_draft_mail_of_a_live_meeting_is_refused"
  - "backend/tests/integration/modules/protocol/test_protocol_draft_and_approval.py:test_draft_mail_goes_to_the_members_and_keeps_the_draft"
  - "frontend/src/app/features/meetings/protocol-bar/protocol-bar.component.spec.ts:draftSentAt"
implementation:
  - backend/app/modules/protocol/draft_mail.py
  - backend/app/modules/meetings/protocol_models.py
  - frontend/vendor/ui-kit/views/protocol/src/protocol-bar-view.component.ts
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# The draft mail waits for the end of the meeting and asks before a repeat

The send of a protocol draft (000925) must be refused while the meeting is live. The protocol
must keep the time of the last send. A second send must ask for a confirmation that shows the
date of the last send.

Reason: A draft from a live Sitzung is not complete. A second mail to all members of the
Gremium is easy to send by mistake.

Test: An integration test that sends the draft of a live meeting and gets a 409, and a
frontend unit test that finds the confirmation with the date on the second send.

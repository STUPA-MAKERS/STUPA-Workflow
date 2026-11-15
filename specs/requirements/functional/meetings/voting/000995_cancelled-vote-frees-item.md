---
id: "000995"
title: A cancelled vote does not block the vote of an application item
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "frontend/src/app/features/meetings/meetings.component.spec.ts:MeetingsComponent"
implementation:
  - backend/app/modules/livevote/service/votes.py
  - frontend/src/app/features/meetings/meeting-session.service.ts
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# A cancelled vote does not block the vote of an application item

The agenda item of an application and the agenda item of a Haushaltsplan take one decision
vote. A cancelled vote must not count for this limit, on the server and in the page. After a
cancel, the page must offer the vote of the item again.

Reason: A vote is cancelled when it cannot reach the quorum or was opened by mistake. The
Gremium must then be able to vote on the item in the same meeting. The server already allowed
this, but the page hid the button.

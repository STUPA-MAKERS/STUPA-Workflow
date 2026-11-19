---
id: "001521"
title: A live meeting page connects and reads again when the page returns
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/core/browser/page-resume.service.spec.ts:PageResumeService"
  - "frontend/src/app/features/meetings/meeting-session.service.spec.ts:liveSetup"
  - "frontend/src/app/core/ws/live-vote.service.spec.ts:PageResumeService"
implementation:
  - frontend/src/app/core/browser/page-resume.service.ts
  - frontend/src/app/features/meetings/meeting-session.service.ts
  - frontend/src/app/core/ws/live-vote.service.ts
  - frontend/src/app/features/public-meeting/guest-session.service.ts
scope:
  - frontend/src/app/core/browser
  - frontend/src/app/core/ws
  - frontend/src/app/features/meetings
  - frontend/src/app/features/voting
  - frontend/src/app/features/public-meeting
---

# A live meeting page connects and reads again when the page returns

The page returns when it becomes visible after it was hidden, when the browser shows it again
from the back-forward cache, or when the device is online again. The events of one return
must count once. On each return, every page with a live meeting channel must close its
channel, open a new channel at once and read its state again: the meeting page, the vote
page, the beamer and the guest page of a public meeting. A page that stopped its tries
(001520) must start again with a count of zero. A page that the user left must open no
channel.

Reason: iOS freezes a PWA in the background and ends its sockets, often without a close
event. The socket then looks open but carries nothing, so the page does not sync after the
user comes back to the meeting.

Test: Frontend unit tests send each kind of return, check that one return counts once, and
check the new channel and the reads of the meeting page and of the vote session.

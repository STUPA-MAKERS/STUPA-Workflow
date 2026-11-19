---
id: "001520"
title: The meeting page opens a dropped live channel again
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/meeting-session.service.spec.ts:liveSetup"
implementation:
  - frontend/src/app/features/meetings/meeting-session.service.ts
scope:
  - frontend/src/app/features/meetings
---

# The meeting page opens a dropped live channel again

When the live channel of the meeting page ends and the page did not close it, the page must
open a new channel after a wait. The wait must grow with each failed try in a row, from one
second up to 15 seconds. After each new channel the page must read the meeting, the agenda, the
attendance and an open protocol again. After eight failed tries in a row the page must stop
and wait for the next return of the page (001521). A frame of the server must reset the count
of failed tries. A frame of a channel that the page replaced must have no effect.

Reason: A deploy, a proxy restart or a short network gap ends the socket. Without a new
channel the page shows a state that no longer changes, and the events of the gap do not come
again, so only a new read shows them.

Test: A frontend unit test drops the channel, checks the new channel and the reads, checks the
stop after the last try, and checks that a replaced channel has no effect.

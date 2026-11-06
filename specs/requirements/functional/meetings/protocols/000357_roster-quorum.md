---
id: "000357"
title: The quorum uses the roster of the meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
---

# The quorum uses the roster of the meeting

The quorum of a protocol must count the members whose term overlaps the meeting, plus every
person with an attendance record. It must not use the members of today.

Reason: A new render of an old meeting then gives the same quorum.

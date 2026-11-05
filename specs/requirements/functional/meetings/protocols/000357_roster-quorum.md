---
id: "000357"
title: The quorum uses the roster of the meeting
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
---

# The quorum uses the roster of the meeting

The quorum of a protocol counts the members whose term overlaps the meeting, plus every person
with an attendance record. It does not use the members of today.

Reason: A new render of an old meeting then gives the same quorum.

---
id: "000094"
title: A meeting with an open vote does not close
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/service/lifecycle.py
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# A meeting with an open vote does not close

The close of a meeting with an open vote must answer 409. The close cancels the draft votes
of the meeting.

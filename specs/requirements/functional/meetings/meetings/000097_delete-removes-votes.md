---
id: "000097"
title: A meeting delete removes its votes
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/applications
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/applications
---

# A meeting delete removes its votes

The delete of a meeting must delete all its votes with their ballots and markers. An Antrag
that such a vote decided must keep its status.

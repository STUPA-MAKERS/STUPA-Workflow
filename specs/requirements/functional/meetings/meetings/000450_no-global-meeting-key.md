---
id: "000450"
title: No global key manages meetings
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote
scope:
  - backend/app/modules/livevote
---

# No global key manages meetings

There must be no global meeting permission except `meeting.view_all`, which only reads.

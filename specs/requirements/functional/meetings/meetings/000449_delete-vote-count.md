---
id: "000449"
title: A meeting delete names the vote count
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/service/lifecycle.py
  - frontend/src/app/features/meetings/delete-meeting-dialog
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/applications
---

# A meeting delete names the vote count

The confirmation dialog of a meeting delete must name the number of votes. The audit entry must
carry the vote count.

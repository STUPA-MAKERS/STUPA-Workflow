---
id: "000028"
title: Only the protokollant opens and closes a meeting vote
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# Only the protokollant opens and closes a meeting vote

Only the protokollant must be able to open and close a vote in a meeting. A holder of
`session.manage` or `vote.manage` in the Gremium and the protokollant must be able to prepare,
cancel and delete a vote.

---
id: "000093"
title: Meeting states move only forward
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# Meeting states move only forward

A meeting goes from `planned` to `live` to `closed`. It must not go back from `live` to
`planned`, and it must not go from `planned` to `closed`. A cancelled meeting is deleted.

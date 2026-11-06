---
id: "000304"
title: No agent token reaches a backup
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/backup
  - backend/worker/backup.py
  - backend/app/modules/auth
---

# No agent token reaches a backup

`backup.manage` must be a forbidden permission for every OAuth token.

Reason: Its holder can read and replace the whole database.

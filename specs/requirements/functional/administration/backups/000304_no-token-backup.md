---
id: "000304"
title: No agent token reaches a backup
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/backup
  - backend/app/worker/backup.py
  - backend/app/modules/auth
---

# No agent token reaches a backup

`backup.manage` is a forbidden permission for every OAuth token.

Reason: Its holder can read and replace the whole database.

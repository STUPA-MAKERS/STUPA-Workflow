---
id: "000303"
title: A restore needs the word RESTORE
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/backup
  - backend/worker/backup.py
  - frontend/src/app/pages/admin/backups
scope:
  - backend/app/modules/backup
  - backend/worker/backup.py
  - frontend/src/app/pages/admin/backups
---

# A restore needs the word RESTORE

The restore dialog and the API must require the literal text `RESTORE`.

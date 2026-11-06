---
id: "000302"
title: A restore first saves the current state
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/backup
  - backend/worker/backup.py
scope:
  - backend/app/modules/backup
  - backend/worker/backup.py
---

# A restore first saves the current state

A restore must first write a `pre_restore` archive. If that fails, the restore must stop. A
`pre_restore` archive and a pinned archive must never count for the retention.

---
id: "000302"
title: A restore first saves the current state
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/backup
  - backend/worker/backup.py
---

# A restore first saves the current state

A restore first writes a `pre_restore` archive. If that fails, the restore stops. A
`pre_restore` archive and a pinned archive never count for the retention.

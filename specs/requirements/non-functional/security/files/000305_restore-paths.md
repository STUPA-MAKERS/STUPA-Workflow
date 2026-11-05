---
id: "000305"
title: A restore writes only inside the bucket
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/backup
  - backend/worker/backup.py
---

# A restore writes only inside the bucket

A restore skips an object key that is absolute, empty or contains a path traversal.

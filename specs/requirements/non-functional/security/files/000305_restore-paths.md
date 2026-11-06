---
id: "000305"
title: A restore writes only inside the bucket
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/backup/service.py
scope:
  - backend/app/modules/backup
  - backend/worker/backup.py
---

# A restore writes only inside the bucket

A restore must skip an object key that is absolute, empty or contains a path traversal.

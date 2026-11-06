---
id: "000465"
title: Backups keep a fixed count and cap uploads
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/settings.py
  - backend/worker/main.py
  - backend/app/modules/backup
scope:
  - backend/app/settings.py
  - backend/worker/main.py
  - backend/app/modules/backup
---

# Backups keep a fixed count and cap uploads

The nightly backup must run at 04:00, after the retention cron. It must keep
`backup_retention_count` (14) archives, besides pinned and `pre_restore` archives. An upload
above 2 GiB must answer 413.

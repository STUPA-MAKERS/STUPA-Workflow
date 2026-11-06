---
id: "000456"
title: Terminal Anträge are anonymized after the retention time
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/worker/retention.py
  - backend/app/modules/privacy
---

# Terminal Anträge are anonymized after the retention time

The cron at 03:30 must anonymize each terminal Antrag older than `retention_months` of its
type, else `privacy_settings.default_retention_months` (default 24). It must not touch budget
rows.

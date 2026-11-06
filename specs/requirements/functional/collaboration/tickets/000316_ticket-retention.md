---
id: "000316"
title: Closed tickets are anonymized after the retention time
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
  - backend/worker/tickets.py
---

# Closed tickets are anonymized after the retention time

A cron anonymizes a ticket whose `closed_at` is older than `tickets.retentionMonths`. The
reporter, the context and the attachments go. Title, body, notes and events stay.

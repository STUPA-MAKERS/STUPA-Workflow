---
id: "000241"
title: The minute cron advances and cleans up
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/worker
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# The minute cron advances and cleans up

Every minute the worker closes overdue votes, fires automatic transitions, deletes unconfirmed
guest Anträge after `confirm_ttl_hours` and sends to-do and poll reminders. Each step is
idempotent and locks each row with `FOR UPDATE SKIP LOCKED`.

---
id: "000241"
title: The minute cron advances and cleans up
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/worker/deadlines.py
  - backend/worker/main.py
scope:
  - backend/worker
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# The minute cron advances and cleans up

Every minute the worker must close overdue votes, fire automatic transitions, delete
unconfirmed guest Anträge after `confirm_ttl_hours` and send to-do and poll reminders. Each
step must be idempotent and must lock each row with `FOR UPDATE SKIP LOCKED`.

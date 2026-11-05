---
id: "000236"
title: A status change is recorded
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/audit
---

# A status change is recorded

Every fired transition writes a status event and a `status_change` audit entry in the same
transaction as the state change.

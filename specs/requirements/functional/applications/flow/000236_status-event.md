---
id: "000236"
title: A status change is recorded
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/audit
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/audit
---

# A status change is recorded

Every fired transition must write a status event and a `status_change` audit entry in the same
transaction as the state change.

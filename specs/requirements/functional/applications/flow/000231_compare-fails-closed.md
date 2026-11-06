---
id: "000231"
title: A guard on a field fails closed
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/shared/guards.py
  - backend/app/modules/flow/context.py
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# A guard on a field fails closed

A `compare` guard must use the type of the field in the pinned form version. A missing field or
an unknown operator must give false.

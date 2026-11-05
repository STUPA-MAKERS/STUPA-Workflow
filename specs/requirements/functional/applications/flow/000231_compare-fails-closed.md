---
id: "000231"
title: A guard on a field fails closed
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# A guard on a field fails closed

A `compare` guard uses the type of the field in the pinned form version. A missing field or
an unknown operator gives false.

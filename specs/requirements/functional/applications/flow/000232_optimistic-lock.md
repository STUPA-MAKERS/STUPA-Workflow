---
id: "000232"
title: A transition fires only from the current state
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/flow/service.py
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# A transition fires only from the current state

A transition must change the state only if the Antrag is still in its source state. A
concurrent change must give 409.

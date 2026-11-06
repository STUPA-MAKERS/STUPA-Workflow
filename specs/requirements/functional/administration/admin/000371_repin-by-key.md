---
id: "000371"
title: A flow save moves Anträge by state key
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/flow/service.py
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
  - backend/app/modules/flow
---

# A flow save moves Anträge by state key

A save of the flow must keep every Antrag in the state with the same key. An Antrag in a
removed state must go to the initial state.

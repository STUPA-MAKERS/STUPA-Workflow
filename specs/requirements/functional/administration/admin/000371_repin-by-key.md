---
id: "000371"
title: A flow save moves Anträge by state key
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
  - backend/app/modules/flow
---

# A flow save moves Anträge by state key

A save of the flow keeps every Antrag in the state with the same key. An Antrag in a removed
state goes to the initial state.

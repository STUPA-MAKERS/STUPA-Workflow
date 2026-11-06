---
id: "000234"
title: No automatic exit from a vote state
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# No automatic exit from a vote state

An automatic transition must not leave a vote state, except through a vote branch. The
validator refuses such a graph, and `auto_advance` never fires out of a vote state.

Reason: Else the platform could approve an Antrag without a vote.

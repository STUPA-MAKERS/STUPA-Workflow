---
id: "000459"
title: A vote state has exactly one pass and one fail branch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/shared/config_schemas.py
scope:
  - backend/app/shared/config_schemas.py
---

# A vote state has exactly one pass and one fail branch

The flow save must refuse a `vote` state without exactly one `pass` and one `fail` transition.
It must refuse a branch on a `normal` state and a cycle of automatic transitions.

Reason: Else a vote result has no next state, or the worker loops.

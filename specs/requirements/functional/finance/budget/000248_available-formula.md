---
id: "000248"
title: The available amount can be negative
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree/view.py
scope:
  - backend/app/modules/budget
---

# The available amount can be negative

`available = allocated − bound − expended + income`. `committed = bound + expended`. The
platform must not clamp `available` at 0.

Reason: A negative value shows an overspent cost centre.

---
id: "000250"
title: The deciding Gremium is inherited
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree_rules.py
  - backend/app/modules/budget/decision.py
scope:
  - backend/app/modules/budget
---

# The deciding Gremium is inherited

The deciding Gremium of a cost centre must be its own value, else the value of the nearest
ancestor.

---
id: "000244"
title: The cost centre is locked during a budget vote
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/budget
---

# The cost centre is locked during a budget vote

While an Antrag is in a vote state with `gremiumSource: "budget"`, a cost centre change must
give 409 `budget_locked_by_vote`, and the `assignBudget*` actions must do nothing.

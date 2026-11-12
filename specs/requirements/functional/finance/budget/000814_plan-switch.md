---
id: "000814"
title: A top-level Kostenstelle has a plan switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_plan_switch_needs_a_top_level_node_with_sides"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_plan_switch_gives_open_years_a_stammplan"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_router.py
scope:
  - backend/app/modules/budget
---

# A top-level Kostenstelle has a plan switch

A top-level Kostenstelle must have the switch "Haushaltsplan". The switch must be off for a
new and for an existing Kostenstelle. The rules for a Haushaltsplan must apply only to a
Kostenstelle below a top-level Kostenstelle with the switch on. The change of the switch
needs `budget.structure`.

Reason: QS-Mittel are no budget of the Studierendenschaft. The Rektorat gives them on a
proposal of the STUPA (QualSiG § 1 (2)), so LHO § 106 and § 108 do not apply to them.

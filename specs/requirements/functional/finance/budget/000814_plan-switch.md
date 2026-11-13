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
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_plan_switch_goes_off_only_without_a_decision"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_plan_write_needs_the_switch"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_is_plain_stammplan"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/admin/budgets
---

# A top-level Kostenstelle has a plan switch

A top-level Kostenstelle must have the switch "Haushaltsplan". The switch must be off for a
new and for an existing Kostenstelle. The rules for a Haushaltsplan must apply only to a
Kostenstelle below a top-level Kostenstelle with the switch on. The change of the switch
needs `budget.structure`.

The switch must go off only while each Haushaltsplan of the budget is a Stammplan in force
that passed no step and belongs to an open fiscal year. The platform must then delete those
plans and keep the allocations. A budget with a different plan must answer 409
`plan_switch_has_plans`. While the switch is off, each write to a plan or to the steps of
the budget must answer 409 `plan_not_enabled`.

Reason: QS-Mittel are no budget of the Studierendenschaft. The Rektorat gives them on a
proposal of the STUPA (QualSiG § 1 (2)), so LHO § 106 and § 108 do not apply to them. A
plan that a body decided is a record, so the switch must not remove it. A plan that only
the switch made holds nothing that the allocations do not hold.

Test: The tests turn the switch on and off for a budget with and without sides, with a Stammplan
of the switch and with a decided plan, and write a plan while the switch is off.

---
id: "000877"
title: A Kostenstelle of a Haushalt with a plan gets a new key or name in a draft
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_draft_gives_a_cost_centre_its_new_name_and_key"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_in_progress_keeps_the_new_name_on_its_way_back"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_draft_paths_follow_the_new_key_of_a_parent"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_a_key_is_taken_by_a_sibling_now_or_in_the_draft"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/tree/nodes.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A Kostenstelle of a Haushalt with a plan gets a new key or name in a draft

In a Haushalt with the plan switch on, the key and the name of a Kostenstelle must change
only in a draft version: the draft of the plan or of a Nachtrag. A direct change must be
refused with the code `plan_draft_only`. The name and the Kürzel of the Haushalt itself
stay changeable, because the Haushalt is no line of the plan. In a Haushalt without a
plan the direct change stays (000246).

The draft must show the new key and the new name, and the path key of each Kostenstelle
below a Kostenstelle with a new key. Every other place must show the values before,
until the version comes into force. When the version comes into force, the key and the
name must apply to the Kostenstelle and then show in every place. A draft that is
deleted changes nothing. A version that leaves the draft keeps the new values in its
lines (000821), and a version that goes back to the draft still holds them.

A new key must be refused when a sibling has it or takes it in the same draft.

Reason: The key and the name of a Kostenstelle are part of the Haushaltsplan that the
Gremium decides. A change beside the plan would change a decided plan without a
decision.

Test: Integration test: a direct rename is refused; a draft sets a name and a key; the
plan read and the export show them and the path keys below; the Kostenstelle keeps its
values until the version is in force and has the new ones after.

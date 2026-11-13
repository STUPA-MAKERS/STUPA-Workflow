---
id: "000854"
title: A Haushaltsplan starts as a draft
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_plan_switch_gives_open_years_a_draft"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_plan_switch_goes_off_only_without_a_decision"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_year_with_a_plan_in_force_refuses_a_direct_allocation"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_is_plain_draft"
  - "backend/tests/integration/test_migrations.py:test_a_plan_of_the_switch_goes_back_to_the_draft"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/tree/allocations.py
  - backend/app/modules/budget/plan_rules.py
  - backend/migrations/versions/fea8282a392b_plan_line_side.py
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/admin/budgets
  - frontend/src/app/pages/budget
---

# A Haushaltsplan starts as a draft

`draft` must be the first state of every plan version, also for a Haushalt without steps.
No action of the platform must make a version that is in force from the start.

When a person sets the plan switch (000814) to on, the platform must give each open fiscal
year of the Haushalt that has no Haushaltsplan a Haushaltsplan with one draft version. The
draft must hold a line for each node below the Haushalt. The Ansatz of a node without a
child must equal its allocation, a parent must hold the sum of its children (000794), and
no Titel has a side (000853). The switch must change no allocation and must ask for
nothing. A closed fiscal year must get no Haushaltsplan (000801).

While a fiscal year has no version in force, the Bewirtschaftung must work with the
allocations as they are, and a person with `budget.structure` must set them by hand as in
a year without a plan (000833). From the first version in force on, 000797 and 000798 hold.

The migration of this rule must turn each Haushaltsplan that only the switch made (one
version in force that passed no step, in an open fiscal year) back into a draft and must
keep the allocations. It must give each open fiscal year of a Haushalt with the switch on
that has no Haushaltsplan a draft.

Reason: A plan that is in force without a decision says more than happened. The decision
of a body or the person with the permission of 000855 brings a plan into force, not a
switch.

Test: The backend tests turn the switch on for a Haushalt with allocations, an open and a
closed year, and read the drafts and the allocations, and set an allocation by hand before
and after a version is in force. The migration test reads a plan of the switch and a year
without a plan after the migration. The page tests read the form without a question and
the allocation field of a year with a draft.

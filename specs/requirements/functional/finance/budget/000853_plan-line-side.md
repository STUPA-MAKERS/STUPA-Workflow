---
id: "000853"
title: The side of a Titel is a part of its plan line
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_line_below_a_titel_has_the_side_of_the_titel"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_node_is_created_without_a_side"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_side_is_refused_off_the_first_level"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_side_changes_in_a_draft_with_its_amounts"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_titel_without_a_side_keeps_the_version_in_the_draft"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_side_of_a_closed_year_does_not_change"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_income_side_takes_the_vermerke_off_the_draft_line"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_decided_version_keeps_the_side_of_its_titel"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_the_side_of_a_line_is_the_side_of_its_titel"
  - "backend/tests/integration/test_migrations.py:test_the_side_moves_from_the_node_to_the_plan_line"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.util.spec.ts:BudgetPlanUtil"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/plan_models.py
  - backend/migrations/versions/fea8282a392b_plan_line_side.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# The side of a Titel is a part of its plan line

A line of a plan version for a Titel (a node directly below the Haushalt) must hold the
side `income` or `expense`, or none while the version is a draft. A line of a Kostenstelle
below a Titel must have the side of the line of its Titel in the same version. A node of
the tree must hold no side, and the tree must answer none.

A person with `budget.structure` must set the side on the plan page, in a draft version
only: in the dialog that adds a Titel to the draft or creates a Titel in it (required field
"Seite"), and in the detail of the line of a Titel (select "Seite").
`PUT /budget-plan-versions/{id}/lines/{budgetId}` must take `side` for a Titel and must
answer 422 `side_not_settable` for a line below a Titel. When the new side is income, the
platform must take the Vermerke and the gesperrt amount off the lines of the Titel and of
each Kostenstelle below it (000816). A version that left the draft must keep its sides:
409 `plan_version_locked`. A closed fiscal year must keep them too (000801).

A version must not leave the draft while a Titel with a line in it has no side, else 422
`plan_side_missing`, and the answer must name these Titel by their path key. The plan page
must list the lines of such Titel in a group of their own ("Ohne Seite") above the two
sides. A new version must copy the sides of the version before it, and a plan that copies
another fiscal year (000837) must copy its sides. The balance of a version (000795) must
count with the sides of that version.

The form "Haushalt bearbeiten" of Verwaltung, the section "Kostenstelle" and the dialog
that creates a node outside a draft must show no field "Seite".

Reason: Titel come and go from one fiscal year to the next, and the plan of a year is the
record of which Titel are income and which are expenses. A side at the tree node holds for
every year at once, so a change for the next year would change the reading of a decided
plan, and Verwaltung would ask for the side of Titel that the next plan no longer has.

Test: The backend tests set the side on each level of a draft, change it with Ansätze and
with Vermerke, try it in a decided version and in a closed year, and move a version without
a side out of the draft. The migration test reads the side of a node on its plan lines. The
page tests set the side in the detail of a line and in the create dialog and read the group
of the Titel without a side.

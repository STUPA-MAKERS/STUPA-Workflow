---
id: "000805"
title: The list of Planung shows the plan as a tree
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# The list of Planung shows the plan as a tree

In the view Planung the list must show the Kostenstellen of the plan as a tree with the
Ansatz of each Kostenstelle, in the groups "Einnahmen" and "Ausgaben" with the sum of each
group. The list must have two filter chips: the fiscal year and the version. The version
chip must name the Stammplan and each Nachtrag. When the person chooses another budget, the
plan, the years, the selected Kostenstelle and the actions of the budget before must go off
the page at once, and a
late answer for the budget before must not come onto the page, so no action changes a plan
that the page does not name.

Reason: The view keeps the list and detail geometry of the Budget tab, and one plan belongs
to one fiscal year and one version.

Test: The component test reads the groups, the rows, the sums and the two filter chips of the
list. One test chooses another budget while the years load and reads that the plan and
the actions of the budget before are gone, and that the years of a budget that the person
left stay off the page. One test reads that the selected Kostenstelle is gone after another
budget is chosen.

---
id: "000829"
title: A Kostenstelle is created in the Budget tab
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/budget/cost-centre/cost-centre-create.component.spec.ts:CostCentreCreateComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/cost-centre/cost-centre-create.component.ts
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
  - backend/app/modules/budget
---

# A Kostenstelle is created in the Budget tab

The Budget tab must offer the action "Kostenstelle anlegen" to a person with
`budget.structure`. The form must take the parent (the budget or a Kostenstelle below it),
the key and the name. For a direct child of a budget with the plan switch on, the form must
also take the side, and the request without a side must answer 422 `plan_side_missing`.
The view Bewirtschaftung must offer the action for a fiscal year without a plan. The view
Planung must offer it only while the shown version is a draft.

Reason: The people who plan and manage a budget add its Kostenstellen where they see the
budget.

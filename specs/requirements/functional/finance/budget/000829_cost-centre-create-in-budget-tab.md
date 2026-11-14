---
id: "000829"
title: A Kostenstelle is created in the Budget tab
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "frontend/src/app/pages/budget/cost-centre/cost-centre-create.component.spec.ts:CostCentreCreateComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_node_is_created_without_a_side"
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
`budget.structure`, as the main action of the page (000209). The form must take the parent
(the budget or a Kostenstelle below it), the key and the name. The form of the view
Bewirtschaftung must take no side, because a node holds none (000853). The view
Bewirtschaftung must offer the action for a fiscal year without a version in force. The view Planung must offer it only while the shown
version is a draft, and the form must then also take the Ansatz and, for a Titel, the side
(000830).

Reason: The people who plan and manage a budget add its Kostenstellen where they see the
budget.

Test: The form tests create a Kostenstelle in a draft with a side and outside a draft without
one, and below a different parent.
The page tests read where the action shows.

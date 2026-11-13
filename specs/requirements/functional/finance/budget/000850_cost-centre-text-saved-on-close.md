---
id: "000850"
title: A typed text of a Kostenstelle is saved when its section goes off the page
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.spec.ts:CostCentreSettingsComponent"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
  - frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.ts
scope:
  - frontend/src/app/pages/budget
---

# A typed text of a Kostenstelle is saved when its section goes off the page

A key or a name that the person typed in the section "Kostenstelle" (000831) and did not
leave must be saved when the section goes off the page, for example by Back on a phone. The
page must read the tree again after this save, on the tab Bewirtschaftung and on the tab
Planung.

Reason: A press that closes the detail does not always take the focus out of the field, and
the typed text would else be lost without a message.

Test: The component tests take the section off the page with a typed name and with a typed
key and read the request and the call of the page. One test of each page reads the tree
after that call.

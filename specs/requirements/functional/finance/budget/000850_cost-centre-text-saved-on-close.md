---
id: "000850"
title: A typed text of a Kostenstelle is saved when its section goes off the page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
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
leave must be saved when the section goes off the page, for example by Back on a phone or
by Back to the other tab of the budget. The budget page that shows when this save ends, the
tab Bewirtschaftung or the tab Planung, must then read the tree again. This read must leave the URL as it is, also when the page
has not taken its budget, Kostenstelle and year from the URL yet, and also when the read fails.

Reason: A press that closes the detail does not always take the focus out of the field, and
the typed text would else be lost without a message. The page that opens reads its tree in
the moment in which the save goes out, so its first tree can hold the text before.

Test: The component tests take the section off the page with a typed name and with a typed
key and read the request and the message for the page that shows. One test of each page
reads the tree after that message. One test of the tab Bewirtschaftung sends the message
before the fiscal years arrive and reads that the page writes no URL. One test of the tab
Planung fails that read on a page without its budget and reads that the page writes no URL.

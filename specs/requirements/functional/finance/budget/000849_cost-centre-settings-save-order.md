---
id: "000849"
title: The settings of a Kostenstelle save one change after the other
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.spec.ts:CostCentreSettingsComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.ts
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# The settings of a Kostenstelle save one change after the other

The section "Kostenstelle" (000831) must save its changes one after the other. A change that
the person makes during a save must be saved after it, for the Kostenstelle that the person
made it for. This holds when changes for more than one Kostenstelle wait, and when the change
sets the field back to the value before. A save, refused or not, must not change the text
that the person types in another field or in a field of another Kostenstelle. The switch
"Aktiv" must stay enabled and keep the keyboard focus while a save runs, and a switch or a
select must show the last choice of the person until its save ends. A text that the person
typed and did not leave must be saved when the section goes off the page, for example by Back
on a phone. A page must drop the answer of a tree read that went out before the read on the
page.

Reason: Two writes that run at the same moment can reach the server in the other order, and
the tree that the page reads after the first one is older than the second one. The last
choice of the person would then be neither saved nor shown.

Test: The component tests type in a field while the page gives the section the saved values
again, press the switch twice while a save runs, read the switch while the tree holds the
state of the first press, type in the name while the save of the key is refused, press the
switch during a save and then the switch of another Kostenstelle, refuse a save of the
Kostenstelle before, set a select back while its save runs, and take the section off the
page with a typed name. The test of the dashboard answers two tree reads in the other order.

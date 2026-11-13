---
id: "000831"
title: A Kostenstelle is edited in the Budget tab
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.spec.ts:CostCentreSettingsComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.ts
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# A Kostenstelle is edited in the Budget tab

The detail of a selected Kostenstelle in the Budget tab must show the section
"Kostenstelle" with its key, its name, its colour, the switch "Aktiv", the Gremium that
sees it and the Gremium that decides. For a direct child of a budget with the plan switch
on, the section must also show the side (000817). When the person selects another
Kostenstelle, each field must show the saved value of that Kostenstelle, also after a text
that was typed and not saved. A person with `budget.structure` must
change each field there, and the platform must save a field when the person leaves it. An
empty key or name must show the saved text again and save nothing. A key or a name that the
rules of the path key refuse (000246) must show the cause below the field and save nothing.
A refused save must show its cause and the saved value of its field again, also in a
select and in the switch. The save of one field, refused or not, must not change the text
that the person types in another field. The switch "Aktiv" must keep the keyboard focus
while its save runs, and a press during a save must be saved after it, for the Kostenstelle
that the person pressed it for. Until that save
ends, the switch must show the last press. A person without
`budget.structure` must not see the section. The state of the plan version must not lock
these fields, because a decided version keeps its own name and key (000821).

Reason: The settings of a Kostenstelle stand beside its amounts, so one place holds all
that a person sets on it.

Test: The component tests change each field and leave it, type a key and a name that the rules
refuse, and read the fields after a refused save. One test types in a field while the page gives
the section the saved values again, and one presses the switch twice while a save runs. One
test reads the switch while the tree holds the state of the first press, one reads the
select of a Gremium after a refused save, and one types in the name while the save of the
key is refused. One test types a text that is not saved and gives the section another
Kostenstelle with the same values. One test presses the switch during a save, gives the
section another Kostenstelle and reads the request.

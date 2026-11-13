---
id: "000827"
title: The steps of a budget are edited in its edit form
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.util.spec.ts:AdminBudgetsUtil"
implementation:
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
  - frontend/src/app/pages/admin/budgets/admin-budgets.util.ts
scope:
  - frontend/src/app/pages/admin/budgets
---

# The steps of a budget are edited in its edit form

The edit form of a budget on the page "Budgets" of Verwaltung (000828) must show the
switch "Haushaltsplan führen" (000814) and, while the switch is on, the list of plan steps.
A person must add a step, name it, choose its Gremium or none, move it and remove it. While
the switch is on, the form must also show each direct child Kostenstelle of the budget
with its side (000817), and the form must not save while a side is missing. The form must
send its requests one after the other and must send no request after one that failed. A
failed load of the steps must show the load error with "Erneut versuchen" in the place of
the steps, must offer no step to add, and must not let the form send a list of steps.

Reason: A list that was not read is not an empty list, and a save of it would replace
the stored steps. The person who sets up a budget sets up the path of its plan in the same place.
The plan switch needs a side on each Kostenstelle, so the form that sets the switch must
set the sides.

Test: The component tests open the edit form, set the sides, add, move and remove steps, save,
and read the requests and their order. A test fails one request and reads that no later request
went out. A test fails the read of the steps and reads the error, the save and the retry.

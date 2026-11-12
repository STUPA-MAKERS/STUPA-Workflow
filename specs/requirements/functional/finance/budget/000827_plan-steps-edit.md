---
id: "000827"
title: The steps of a budget are edited in its edit form
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.util.spec.ts:movedStep"
implementation:
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
  - frontend/src/app/pages/admin/budgets/admin-budgets.util.ts
scope:
  - frontend/src/app/pages/budget
---

# The steps of a budget are edited in its edit form

The edit form of a budget on the page "Budgets" of Verwaltung (000828) must show the
switch "Haushaltsplan führen" (000814) and, while the switch is on, the list of plan steps.
A person must add a step, name it, choose its Gremium or none, move it and remove it.

Reason: The person who sets up a budget sets up the path of its plan in the same place.

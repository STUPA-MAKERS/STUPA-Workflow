---
id: "000834"
title: An inactive Kostenstelle is hidden in the Budget tab
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - frontend/src/app/pages/budget
  - backend/app/modules/budget
  - mcp
---

# An inactive Kostenstelle is hidden in the Budget tab

The Budget tab and each Kostenstelle picker must not show a Kostenstelle that is not
active, and none below it. A person with `budget.structure` must still see it in the Budget
tab, marked "inaktiv", so that the person can set it active again. A Kostenstelle must have
no separate flag that hides it in the Budget tab: the platform must not keep
`hiddenInBudget`.

Reason: Two switches with the same effect make a person choose between them without a
difference.

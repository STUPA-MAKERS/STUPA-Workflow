---
id: "000139"
title: A fiscal year closes and reopens
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree/fiscal_years.py
  - backend/app/modules/budget/tree_router.py
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A fiscal year closes and reopens

A holder of `budget.structure` must be able to close and reopen a fiscal year. "Haushaltsjahr
abschließen" must be in the ⋮ menu of the selected year.

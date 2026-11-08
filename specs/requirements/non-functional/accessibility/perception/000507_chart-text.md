---
id: "000507"
title: A chart has a text alternative
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/pages/budget/budget-sunburst.component.spec.ts:BudgetSunburstComponent"
implementation:
  - frontend/src/app/pages/budget/budget-sunburst.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A chart has a text alternative

A chart must also show its values as a table or a list that a screen reader can read.

Reason: WCAG 1.1.1. A screen reader cannot read a chart that is only a drawing.

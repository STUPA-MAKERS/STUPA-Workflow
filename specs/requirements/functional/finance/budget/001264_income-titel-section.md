---
id: "001264"
title: Income nodes are listed under "Einnahmen"
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-17
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/budget-dashboard.component.html
  - frontend/src/app/pages/budget/budget-dashboard.component.scss
scope:
  - frontend/src/app/pages/budget
---

# Income nodes are listed under "Einnahmen"

The section "Auslastung" of the Haushalt page must list only the nodes on the expense
side. The nodes on the income side must be listed in a section "Einnahmen" with the columns
"Ansatz", "Erreicht" (percent) and "Ist" and the bar of 001263. A Haushalt with both sides
shows both sections, one below the other. A selected income node must show no section
"Verteilung", because the distribution figures are expense figures.

Reason: Utilisation, Beantragt and Verfügbar have no meaning for an income node.

Test: The page tests read both sections of a Haushalt and the sections of an income Titel
with Kostenstellen.

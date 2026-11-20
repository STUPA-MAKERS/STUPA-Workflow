---
id: "001872"
title: Buchungen ansehen opens the bookings of the cost centre and the year
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
scope:
  - frontend/src/app/pages/budget
---

# Buchungen ansehen opens the bookings of the cost centre and the year

"Buchungen ansehen" on the page of a Kostenstelle must open
`/expenses?budget=<id>&fiscalYear=<id>` with the selected Kostenstelle and the selected
Haushaltsjahr. The list must show the bookings of the Kostenstelle and of its subtree in that
year. Without a selected year the link must carry the Kostenstelle only.

Reason: The cost centre page shows the figures of one Haushaltsjahr, so a list of the bookings
of every year does not match the figures that the person clicked from.

Test: the dashboard spec checks the query parameters of the menu item and of the button.

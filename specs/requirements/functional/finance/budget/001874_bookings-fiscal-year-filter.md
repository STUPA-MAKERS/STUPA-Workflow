---
id: "001874"
title: The bookings list filters by Haushaltsjahr
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/expenses/expenses.component.spec.ts:ExpensesComponent"
implementation:
  - frontend/src/app/pages/expenses/expenses.component.ts
  - frontend/src/app/pages/expenses/expenses.component.html
  - frontend/src/app/pages/expenses/expenses-list.state.ts
  - frontend/src/app/pages/expenses/expense-transfers.state.ts
scope:
  - frontend/src/app/pages/expenses
---

# The bookings list filters by Haushaltsjahr

The bookings list must show a chip "Haushaltsjahr" while the Kostenstelle chip has a value. Its
options must be "Alle Jahre" and the years of the top Kostenstelle of that value. The chosen
year must be the query parameter `fiscalYear` and must filter the bookings, the transfers and
the export. A Kostenstelle of another top Kostenstelle must clear the year, and so must
"Kostenstelle: Alle". A `fiscalYear` without `budget` in the URL must drop.

Reason: A fiscal year belongs to one top Kostenstelle, so the chip has no options without one.
A hidden year filter would narrow the list with no chip that shows it.

Test: the bookings spec checks the URL, the request, the options and the clear.

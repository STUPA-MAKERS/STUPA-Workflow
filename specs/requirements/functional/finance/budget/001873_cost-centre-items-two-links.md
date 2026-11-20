---
id: "001873"
title: The cost centre card lists Anträge and bookings and links to both lists
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/budget-items/budget-item-list.component.spec.ts:BudgetItemListComponent"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.html
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/budget-items
scope:
  - frontend/src/app/pages/budget
---

# The cost centre card lists Anträge and bookings and links to both lists

The card "Anträge und Buchungen" of a Kostenstelle must list Anträge and bookings in one list,
each with a type icon. The head of the card must have two buttons: "Anträge ansehen" opens
`/applications?budget=<id>`, and "Buchungen ansehen" opens the bookings as
`F/finance/budget/001872` says. On a phone the buttons must read "Anträge" and "Buchungen",
so the heading keeps its line. A reader without a budget role must see "Anträge ansehen"
only. A card without items must show no button.

Reason: The one button "Alle ansehen" opened a dialog with both kinds, which the person then
had to filter again. The two list pages already have the filters, the export and the detail.

Test: the dashboard spec checks both buttons, their links and the reader without a budget role.

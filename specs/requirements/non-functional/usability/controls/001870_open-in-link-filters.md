---
id: "001870"
title: A link to a list page opens the list filtered to its source
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/features/gremien/gremium-meetings/gremium-meetings.component.spec.ts:GremiumMeetingsComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - frontend/src/app/features/gremien/gremium-meetings/gremium-meetings.component.html
  - frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.ts
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
scope:
  - frontend/src/app/features/gremien
  - frontend/src/app/pages/budget
  - frontend/src/app/features/meetings
  - frontend/src/app/pages/expenses
  - frontend/src/app/pages/applications
---

# A link to a list page opens the list filtered to its source

A link or a menu item that opens a list page from one element ("In „Sitzungen“ öffnen",
"Buchungen ansehen", "Anträge ansehen", "Abstimmungen") must open the list with the filter of
that element set. The filter must be a query parameter of the list page with an English name,
and the list must show it as its filter chip. A filter that the list page does not have must
not go into the link.

Reason: An unfiltered list after a click on one Gremium or one Kostenstelle shows the rows of
every Gremium or of the whole Haushalt, so the person has to set the filter again by hand.

Test: the specs of the Gremium tabs and of the cost centre page check the query parameters of
each link.

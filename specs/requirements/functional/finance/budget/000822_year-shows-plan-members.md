---
id: "000822"
title: A year with a plan shows only its Kostenstellen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/cost-centre-select/cost-centre-select.component.spec.ts:CostCentreSelectComponent"
  - "frontend/src/app/pages/budget/cost-centre/cost-centre.util.spec.ts:CostCentreUtil"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/cost-centre/cost-centre.util.ts
  - frontend/src/app/pages/budget/cost-centre-select/cost-centre-select.component.ts
scope:
  - frontend/src/app/pages/budget
  - frontend/src/app/pages/expenses
  - frontend/src/app/pages/applications
---

# A year with a plan shows only its Kostenstellen

The view Bewirtschaftung must show, for a fiscal year that has a version in force, only a
Kostenstelle that has a line in that version or a booking or an Antrag in that year. A
Kostenstelle picker that chooses for one fiscal year must offer only a Kostenstelle with a
line in the version in force of that year: the picker of the booking form, of the transfer
form and of the assignment of an Antrag. The top-level Kostenstelle must always show. A
year without a plan must show each Kostenstelle. A picker that does not choose for one
fiscal year must show each active Kostenstelle: a filter of a list and the panel that
changes many bookings at once.

Reason: A Kostenstelle that is not in the plan of a year has no Ansatz there. It stays
visible while it holds a booking, because the booking must be found and moved. A filter
spans the years, so the plan of one year cannot limit it.

Test: The dashboard test picks a year with a plan in force and reads the tree. The picker test
gives the picker a fiscal year and reads its options.

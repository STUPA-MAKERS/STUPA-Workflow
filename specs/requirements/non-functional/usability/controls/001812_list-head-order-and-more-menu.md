---
id: "001812"
title: A list head has one order and the export in the ⋮ menu
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/applications/applications-list.component.spec.ts:ApplicationsListComponent"
  - "frontend/src/app/pages/expenses/expenses.component.spec.ts:ExpensesComponent"
  - "frontend/src/app/pages/invoices/invoices.component.spec.ts:InvoicesComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - frontend/src/app/pages/applications/applications-list.component.html
  - frontend/src/app/pages/applications/applications-list.component.ts
  - frontend/src/app/pages/expenses/expenses.component.html
  - frontend/src/app/pages/expenses/expenses.component.ts
  - frontend/src/app/pages/invoices/invoices.component.html
  - frontend/src/app/pages/invoices/invoices.component.ts
  - frontend/src/app/pages/budget/budget-dashboard.component.html
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
scope:
  - frontend/src/app/pages/
---

# A list head has one order and the export in the ⋮ menu

On a wide screen the head of a list must show its buttons in this order:

1. `Mehrere auswählen` (icon `boxok`, spec 001811), if the list has a multiple selection.
2. `Sortieren` (icon `sort`), if the list has a sort.
3. The ⋮ menu `Weitere Aktionen`.

The export, the import and the other page actions must be entries of the ⋮ menu. They must
not have an icon button of their own. A list that has such an action and no ⋮ menu gets one.
The head of the Haushalt detail puts its export in its ⋮ menu too.

On a phone the head has one menu (spec 001811). Its order is: the sort, the entries of the
⋮ menu, `Mehrere auswählen`, `Aktualisieren`.

Reason: The heads of the Anträge, the Buchungen and the Rechnungen had the export or the
import as a separate icon button, each list in a different place. The same action must be
in the same place in every list.

Test: Unit tests of the Anträge, the Buchungen, the Rechnungen and the Haushalt expect the
export or the import in the ⋮ menu and no button of its own.

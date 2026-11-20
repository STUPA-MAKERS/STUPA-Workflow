---
id: "001811"
title: Every list with a multiple selection works the same
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/invoices/invoices.component.spec.ts:InvoicesComponent"
  - "frontend/src/app/pages/expenses/expenses.component.spec.ts:ExpensesComponent"
  - "frontend/src/app/pages/expenses/bulk-panel/bulk-panel.component.spec.ts:BulkPanelComponent"
implementation:
  - frontend/src/app/pages/invoices/invoices.component.html
  - frontend/src/app/pages/invoices/invoices.component.ts
  - frontend/src/app/pages/expenses/expenses.component.html
  - frontend/src/app/pages/expenses/expenses.component.ts
  - frontend/src/app/pages/expenses/bulk-panel/bulk-panel.component.html
scope:
  - frontend/src/app/pages/
---

# Every list with a multiple selection works the same

The Anträge, the Buchungen and the Rechnungen have a multiple selection. It must work the
same in each of these lists:

1. The head of the list has the icon button `Mehrere auswählen` (icon `boxok`). On a phone
   the entry is in the menu of the head.
2. A long press on a row starts the selection with that row (spec 001810). On a phone the
   swipe to the left does the same.
3. In the selection each row shows a checkbox, and a click on a row toggles it. The row
   menu, the swipe to the right and the floating button are not shown.
4. The selection bar under the search shows the count, `Alle wählen` and `Auswahl
   beenden`, and the actions of the list as icon buttons in one button group, in every
   layout.
5. A panel or a sheet that shows the selection in place of the detail has the head bar of
   `Antrag bearbeiten` (spec 001890): the icon `boxok`, the count as the title, the
   details as the subtitle, and `Abbrechen` at the end.

The actions of the Rechnungen are `Als bezahlt markieren` (for the selected open
invoices) and `Löschen`. The bulk delete of the Rechnungen has the limits of the
Buchungen: at most five rows, and no delete after `Alle wählen`.

Only a person who can manage the list gets the selection.

Reason: The Buchungen had the selection only in the menu of the head, their bar showed a
lone text button side by side, and the Rechnungen had no selection.

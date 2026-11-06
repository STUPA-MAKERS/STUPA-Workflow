---
id: "000417"
title: Work lists follow the Anträge pattern
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/shell/src/list-detail-page.ts
  - frontend/src/app/pages/expenses/expenses.component.ts
  - frontend/src/app/pages/invoices/invoices.component.ts
  - frontend/src/app/pages/tasks/tasks.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Work lists follow the Anträge pattern

Buchungen, Rechnungen and Aufgaben must use the list and detail pattern of Anträge. The account
area must use the two-pane frame of Verwaltung.

---
id: "001261"
title: An expense booking on an income Titel is a Rückzahlung
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-17
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_tree_gives_an_income_titel_its_ansatz_and_ist"
  - "frontend/src/app/pages/budget/budget-items/budget-item-list.component.spec.ts:BudgetItemListComponent"
implementation:
  - backend/app/modules/budget/tree/view.py
  - frontend/src/app/pages/budget/budget-items/budget-item-list.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# An expense booking on an income Titel is a Rückzahlung

A booking of the kind `expense` on a node that is income in the fiscal year of the
booking must count as a Rückzahlung: it lowers the Ist of the node (001260) and does not count
as "Ausgegeben". The list "Anträge und Buchungen" of the Haushalt page must name such a
booking "Rückzahlung" instead of "Ausgabe".

Reason: Money that goes back out of an income Titel (a refund of a fee, a returned
deposit) is an Absetzung from the income, not an expense of the Haushalt.

Test: The backend test books an income and a Rückzahlung on an income Titel and reads the
net Ist. The list test reads the label of an expense on an income cost centre in its year
and in another year.

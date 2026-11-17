---
id: "001260"
title: An income Titel shows Ansatz, Ist and the deviation
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-17
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_tree_gives_an_income_titel_its_ansatz_and_ist"
  - "backend/tests/unit/modules/budget/test_budget_tree_rules.py:test_build_forest_income_actual_and_planned"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - backend/app/modules/budget/tree/view.py
  - backend/app/modules/budget/tree_rules.py
  - backend/app/modules/budget/tree_schemas.py
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# An income Titel shows Ansatz, Ist and the deviation

A node is income in a fiscal year when the plan version in force of that year puts its
Titel on the side `income` (000853, 001030). For such a node the Haushalt page must show three
tiles instead of six:

- **Ansatz**: the Ansatz of its line in the version in force.
- **Ist**: the booked income minus the Rückzahlungen (001261). It is the tile in the accent
  colour.
- **Mehreinnahmen** or **Mindereinnahmen**: `Ist − Ansatz`. The label follows the sign;
  at 0 the label is "Abweichung".

The page must not show "Beantragt", "Gebunden", "Ausgegeben" or "Verfügbar" for such a node.
The tree answer (`GET /budgets`) must give, per fiscal year, `planned` (the Ansatz of the line
in the version in force, `null` without a line) and `incomeActual` (the Ist of the income
side, rolled up like income), also for an income line whose allocation stays 0 (000797).
A Haushalt without a plan has no sides and stays as it is.

Reason: An income Titel holds money that comes in, not money to spend. The plan in force
gives it the allocation 0, so the expense figures showed "Ansatz 0" and an income as
"Verfügbar". Ansatz, Ist and the deviation are how a Haushaltsrechnung reads an income
Titel.

Test: The backend tests read `planned` and `incomeActual` of an income Titel. The page tests
read the three tiles of an income Titel and the label of the deviation.

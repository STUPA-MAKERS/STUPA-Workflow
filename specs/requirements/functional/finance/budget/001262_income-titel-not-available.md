---
id: "001262"
title: The Ist of an income Titel does not raise the Verfügbar of the Haushalt
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
  - backend/app/modules/budget/plan_export.py
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# The Ist of an income Titel does not raise the Verfügbar of the Haushalt

The bookings of a node that is income in the fiscal year must not count in `income`,
`expended` or `available` of that node or of the nodes above it (exception to 000247 and
000248). They count only in `incomeActual`, which rolls up. A node above an income Titel
must show `incomeActual` in a tile of its own, "Einnahmen (Ist)", before "Verfügbar". An
income on a node on the expense side (for example a refund of an expense) still raises the
Verfügbar as before. More income becomes money to spend only through a Nachtrag (000799).
The Ist of the year before in the plan export and on the plan page must read
`income + incomeActual` for an income line.

Reason: The plan is balanced (000795), so the expense Ansätze are already covered by the
income Ansätze. Counting the Ist of the income on top covers the same expense twice.

Test: The backend tests read the Verfügbar of the Haushalt with an income on an income Titel
and with an income on an expense node. The page test reads the tiles of the Haushalt.

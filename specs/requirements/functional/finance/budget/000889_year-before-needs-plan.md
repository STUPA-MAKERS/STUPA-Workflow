---
id: "000889"
title: The columns of the year before show only when that year has a plan
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_the_ist_needs_a_plan_in_the_year_before"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_exports_with_the_year_before_and_the_version_before"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/plan_export.py
  - backend/app/modules/budget/tree/plan_exports.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget/plan
---

# The columns of the year before show only when that year has a plan

The page of a Haushaltsplan (000808, 000815) and its export (000875) must show the Ansatz
and the Ist of the year before only when the year before has a plan in force. Without
one, the tables, the detail of a line, the XLSX file and the PDF file must have neither
of the two. The column "Änderung" stays.

Reason: Without a plan in the year before there is no Ansatz to compare with, and the
Ist holds only zeros and reads like a year without spending.

Test: Unit test: the headings of an export with a year before that has no plan in force
have neither "Ansatz" nor "Ist" of that year. Component test: the tables and the detail
of a line show the two only with a plan in force in the year before.

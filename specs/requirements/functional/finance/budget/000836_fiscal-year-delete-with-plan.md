---
id: "000836"
title: A fiscal year with a decided plan cannot be deleted
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_fiscal_year_with_a_decided_plan_is_not_deleted"
  - "backend/tests/unit/modules/budget/test_tree_service_cov.py:test_delete_fiscal_year_with_bookings_409"
  - "backend/tests/unit/modules/budget/test_tree_service_cov.py:test_delete_fiscal_year_with_allocations_409"
  - "backend/tests/unit/modules/budget/test_tree_service_cov.py:test_delete_fiscal_year_with_applications_409"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.util.spec.ts:AdminBudgetsUtil"
implementation:
  - backend/app/modules/budget/tree/fiscal_years.py
  - backend/app/modules/budget/tree_rules.py
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
  - frontend/src/app/pages/admin/budgets/admin-budgets.util.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/admin/budgets
---

# A fiscal year with a decided plan cannot be deleted

The delete of a fiscal year must answer 409 `fiscal_year_has_plan` when its Haushaltsplan
has a version that left `draft`. A plan that holds only a draft must go with the fiscal
year, and the audit entry of the delete must say so. A fiscal year in use must answer 409
with the code of its cause: `fiscal_year_has_bookings`, `fiscal_year_has_allocations` or
`fiscal_year_has_applications`. The page "Budgets" must name the cause from the code.

Reason: A conditional delete must never remove a record without a word (000161). A decided
plan is a record, and a draft binds nobody.

Test: The backend tests delete a fiscal year with a draft plan, with a decided plan, with
bookings, with allocations and with Anträge. The component tests read the message of each
refusal.

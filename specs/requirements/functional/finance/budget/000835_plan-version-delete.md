---
id: "000835"
title: A draft version can be deleted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_draft_version_is_deleted"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A draft version can be deleted

A person with `budget.structure` must delete a plan version in `draft`
(`DELETE /budget-plan-versions/{id}`). The delete must remove the lines of the version.
When the plan has no other version, the delete must remove the plan too. A version in a
different state must answer 409 `plan_version_locked`. The delete must write an audit
entry. The plan page must offer "Entwurf löschen" for a draft and must ask for a
confirmation first (000840).

Reason: A Nachtrag or a plan that a person created by mistake must not stay until a body
decides it (000161). A decided version is a record and stays.

Test: The backend test deletes a draft Nachtrag, a draft Stammplan and a decided version. The
component test deletes a draft after the confirmation.

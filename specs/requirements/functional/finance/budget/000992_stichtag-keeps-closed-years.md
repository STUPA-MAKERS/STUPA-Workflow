---
id: "000992"
title: A new Stichtag moves only the fiscal years that are not closed
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/budget/test_budget_tree_service.py:test_a_new_stichtag_moves_only_the_years_that_are_not_closed"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
implementation:
  - backend/app/modules/budget/tree/nodes.py
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/admin
---

# A new Stichtag moves only the fiscal years that are not closed

A change of the Stichtag of a Haushalt must set the start and the end of each fiscal year that
is not closed. A closed fiscal year must keep its start and its end. The form must ask before
it saves a new Stichtag: it must say that the open years move, that the closed years keep their
dates and that each booking stays in its year. The change must go out only after the person
confirms it.

Reason: The books of a closed year are done, so its dates must not move afterwards. A new
Stichtag changes which dates belong to an open year, and a person who changes it must know
that before the save.

Test: Integration test: after a new Stichtag a closed year has its old dates and an open year
has the new ones. Component test: the first press on the save shows the note and sends
nothing, the second press sends the change.

---
id: "000862"
title: A budget says if its new plan lines start deckungsfähig
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_new_expense_line_starts_deckungsfaehig_when_the_budget_says_so"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_lines_of_a_titel_start_deckungsfaehig_when_it_becomes_expense"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_default_changes_no_line_that_exists"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_starts_coverable"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
implementation:
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/tree/nodes.py
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/admin/budgets
---

# A budget says if its new plan lines start deckungsfähig

A top-level budget must hold the setting "Ausgaben standardmäßig deckungsfähig"
(`planCoverableDefault`, yes or no, no at the start). A person with `budget.structure` sets
it where the plan switch of the budget is set. With the setting on, the platform must set
the Vermerk "deckungsfähig" (000816) on a plan line of a draft at the moment the line becomes
an expense line:

- a new line below a Titel with the side expense, and
- the line of a Titel and each line below it, when the Titel gets the side expense and did
  not have it before (000853).

A request that names "deckungsfähig" for its line wins over the setting. The switch per
line stays, so a person can take the Vermerk off one line. A change of the setting must
change no line that exists. A copy of a version keeps the Vermerke of its source. With the
setting off, a line starts without the Vermerk.

Reason: The Finanzordnung of the Studierendenschaft (§ 5) says that the Titel cover each
other unless the plan says otherwise. For such a budget the Vermerk is the rule and its
absence is the exception, so nobody should set it on every line by hand. Other budgets
follow LHO § 20, where a Vermerk is the exception.

Test: The backend test sets the setting on and off, sets the side of a Titel with lines
below it, creates a line below an expense Titel with and without a named Vermerk, and
changes the setting with lines in a draft. The page test sets the setting in the dialog of
the budget.

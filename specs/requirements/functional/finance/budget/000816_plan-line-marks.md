---
id: "000816"
title: A plan line of an expense holds the Vermerke
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_set_line_checks_the_node_and_the_marks"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_income_side_takes_the_vermerke_off_the_draft_line"
implementation:
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
---

# A plan line of an expense holds the Vermerke

A plan line of an expense Kostenstelle must hold the Vermerke "übertragbar" and
"deckungsfähig" as yes or no and a gesperrt amount from 0 € to the Ansatz, else 422
`plan_blocked_above_amount`. A line of an income Kostenstelle must not hold a Vermerk, else
422 `plan_marks_income`. When a Kostenstelle gets the side income (000817), the platform
must take the Vermerke and the gesperrt amount off its lines in each draft.

Reason: LHO § 19, § 20 and § 22 name these Vermerke as a part of the plan. The plan shows them
before the platform applies them.

Test: The test sets the Vermerke of an expense line and of an income line, and a gesperrt amount
above the Ansatz, and sets the side of a Kostenstelle with Vermerke to income.

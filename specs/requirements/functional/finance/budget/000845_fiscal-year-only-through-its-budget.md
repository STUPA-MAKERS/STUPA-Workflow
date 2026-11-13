---
id: "000845"
title: A fiscal year changes only through its own budget
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_year_changes_only_through_its_own_budget"
implementation:
  - backend/app/modules/budget/tree/fiscal_years.py
scope:
  - backend/app/modules/budget
---

# A fiscal year changes only through its own budget

A request that changes, closes, reopens or deletes a fiscal year must name the budget of
that year. A request that names another budget must answer 404 and must change nothing.

Reason: The request takes the lock and the start date of the budget that it names
(000842, 000251). With another budget the year gets the dates of that budget, and a plan
write of its own budget does not wait.

Test: The integration test changes, closes and deletes a year through another budget and
reads the 404 and the unchanged year.

---
id: "000141"
title: A fiscal year in use is not deleted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/budget/test_budget_tree_service.py:test_a_year_with_allocations_of_zero_is_deleted"
implementation:
  - backend/app/modules/budget/tree/fiscal_years.py
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A fiscal year in use is not deleted

A delete of a fiscal year with bookings or allocations must answer 409. An allocation of 0
does not count and goes with the year, because an allocation can only be set to 0, not removed.

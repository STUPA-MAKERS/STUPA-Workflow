---
id: "000846"
title: An allocation by hand has at most two decimal places
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_an_allocation_has_two_decimal_places"
implementation:
  - backend/app/modules/budget/tree_schemas.py
scope:
  - backend/app/modules/budget
---

# An allocation by hand has at most two decimal places

A request that sets an allocation with more than two decimal places must answer 422. The
answer and the audit entry must hold the amount with two decimal places, as the database
holds it, and an amount of minus zero as `0.00`.

Reason: The database rounds a third decimal place. The audit entry then holds an amount
that was never stored, and the revert of that entry is refused for good, because the stored
amount never matches it (000255).

Test: The unit test gives the schema an amount with three decimal places, minus zero and an
amount in another notation, and reads the refusal and the two decimal places.

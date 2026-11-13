---
id: "000842"
title: A write beside a Haushaltsplan takes the lock of its budget
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_write_beside_a_plan_waits_for_the_lock_of_its_budget"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_plan_that_went_while_a_write_waited_is_not_found"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_key_taken_at_the_same_moment_is_a_conflict"
  - "backend/tests/unit/shared/test_error_contract.py:test_a_text_that_the_database_refuses_is_a_422"
implementation:
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/tree/nodes.py
  - backend/app/modules/budget/tree/fiscal_years.py
  - backend/app/shared/errors.py
scope:
  - backend/app/modules/budget
  - backend/app/shared
---

# A write beside a Haushaltsplan takes the lock of its budget

Each write that changes a Haushaltsplan, or that a rule of the plan reads, must first take
a row lock on the top-level Kostenstelle of the plan: a write of a version, a line or a
step, the plan steps and the plan switch of a budget, the side of a Kostenstelle, the delete
of a Kostenstelle, and the change, the delete, the close and the reopen of a fiscal year.
The order of the locks must be: the vote, the top-level Kostenstelle, the plan, the audit
log. A request that waited must check its rules again on the data it then reads, and it
must answer 404 when its plan is gone and the 409 or 422 of its rule when the rule no
longer holds. Two such requests at the same moment must never answer 500. A text that the
database cannot store must answer 422.

Reason: Two requests that each read before the other writes both pass a rule that only one
of them may pass, for example a delete of a Kostenstelle beside a version that comes into
force. Locks in two orders stop each other, and the database then ends one request with an
error.

Test: The integration tests hold the lock of a budget in one session and start each write
in a second session, read that it waits, and read its answer after the first session ends.
One test deletes the plan while a write waits. The unit test gives the error handler each
SQLSTATE of a refused text.

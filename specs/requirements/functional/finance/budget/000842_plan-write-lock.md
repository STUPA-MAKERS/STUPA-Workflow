---
id: "000842"
title: A write in the tree of a budget takes the lock of the budget
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_write_beside_a_plan_waits_for_the_lock_of_its_budget"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_plan_that_went_while_a_write_waited_is_not_found"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_that_went_while_a_write_waited_is_not_found"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_allocation_that_waited_for_the_plan_switch_is_refused"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_key_taken_at_the_same_moment_is_a_conflict"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_close_of_a_step_vote_locks_the_plan_before_the_audit_entry"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_kostenstelle_that_went_while_a_write_waited_is_not_found"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_gremium_that_went_while_a_write_waited_is_not_valid"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_budget_for_a_gremium_that_goes_beside_the_create_is_not_found"
implementation:
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/tree/nodes.py
  - backend/app/modules/budget/tree/fiscal_years.py
  - backend/app/modules/budget/tree/allocations.py
  - backend/app/modules/budget/tree/revert.py
  - backend/app/modules/voting/service.py
scope:
  - backend/app/modules/budget
  - backend/app/modules/voting
---

# A write in the tree of a budget takes the lock of the budget

Each write that changes a Haushaltsplan, or that a rule of the plan reads, must first take
a row lock on the top-level Kostenstelle of its tree: a write of a version, a line or a
step, the plan steps and the plan switch of a budget, the create, the change, the delete
and the side of a Kostenstelle, an allocation by hand, the revert of one of these from the
audit log, and the create, the change, the delete, the close and the reopen of a fiscal
year. The platform must find the top-level Kostenstelle by the parents of the Kostenstelle
and not by its path key. The order of the locks must be: the vote, the top-level
Kostenstelle, the plan, the audit log. A request must read its data after it has the lock.
A request that waited must answer 404 when its Kostenstelle, its plan or its version is
gone, and the 409 or 422 of its rule when the rule no longer holds. Two such requests at
the same moment must never answer 500.

Reason: Two requests that each read before the other writes both pass a rule that only one
of them may pass, for example a delete of a Kostenstelle beside a version that comes into
force, or an allocation by hand beside the plan switch. Locks in two orders stop each
other, and the database then ends one request with an error. A key can change (000246), so
a path key that a request read before its wait can name no Kostenstelle after it.

Test: The integration test holds the lock of a budget in one session and starts each write of the list above in a second session, reads that it waits, and reads its answer after the first session
ends. One test each deletes the Kostenstelle, the plan and the version while a write waits, and one turns
the plan switch on while an allocation waits. One test reads that the close of a step vote
holds the lock of the plan before it writes its audit entry.

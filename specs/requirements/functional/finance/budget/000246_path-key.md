---
id: "000246"
title: A cost centre has a stable path key
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_tree_service.py:test_rename_key_recomputes_descendant_paths"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_node_schemas_refuse_what_they_cannot_store"
  - "backend/tests/unit/modules/budget/test_budget_tree_rules.py:test_is_valid_key"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_key_that_another_request_holds_is_a_conflict"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_only_a_taken_key_is_a_key_conflict"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_top_level_key_waits_for_the_lock_of_the_top_level_keys"
implementation:
  - backend/app/modules/budget/tree_rules.py
  - backend/app/modules/budget/tree/nodes.py
scope:
  - backend/app/modules/budget
---

# A cost centre has a stable path key

A cost centre must have a `key` and a server-made `path_key` (its form: 000878). A `key` must hold only letters and digits, at most 64; a key with a line feed at its end
must answer 422. The parent of a cost centre must not
change. A person with `budget.structure` can change the `key`, and the platform must then
make the `path_key` of the cost centre and of each cost centre below it again. A `key` that a sibling has must answer 409 `budget_key_exists`, also when two requests
take the key at the same moment and also at the top level. The platform must give that
answer only for a key that a sibling has, and for no other error of the write. Only a top-level cost centre must
have a Gremium and a fiscal start date.

Reason: The path key is the Titel number that a person reads in the plan and in a booking,
and a number that was typed wrong must be correctable. A decided plan keeps its own copy
of the key (000821), so a change does not touch a record.

Test: The service tests rename a key with and without descendants and with the key of a
sibling, give a key with a line feed, and change a key that another request holds.

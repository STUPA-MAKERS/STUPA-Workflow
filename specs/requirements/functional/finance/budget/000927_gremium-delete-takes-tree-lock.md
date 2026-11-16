---
id: "000927"
title: The delete of a Gremium takes the lock of each tree that names it
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_delete_of_a_gremium_waits_for_the_lock_of_a_tree_that_names_it"
implementation:
  - backend/app/modules/admin/service/gremien.py
  - backend/app/modules/budget/tree/service_base.py
scope:
  - backend/app/modules/admin
  - backend/app/modules/budget
---

# The delete of a Gremium takes the lock of each tree that names it

The delete of a Gremium must first take the lock of the tree (000842) of each Kostenstelle
that names the Gremium as its view Gremium or as its deciding Gremium, and only then the
lock of the Gremium. The delete must wait for a write in such a tree, and must then clear
the field on each of those Kostenstellen. A delete of a Gremium and a write in a tree at the
same moment must never answer 500.

Reason: The delete clears the fields through the database, so it writes in those trees. A
write in a tree takes the lock of the tree first and reads the Gremium second (000842). A
delete that takes the two locks in the other order stops that write and is stopped by it,
and the database then ends one of the two requests with an error.

Test: The integration test holds the lock of a tree in one session and starts the delete of
a Gremium that a Kostenstelle of that tree names in a second session. It reads that the
delete waits, and after the first session ends, that the Gremium is gone and the field is
empty.

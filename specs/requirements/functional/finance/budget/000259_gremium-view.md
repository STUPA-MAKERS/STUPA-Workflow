---
id: "000259"
title: Gremium members see their cost centres
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_gremium_of_the_view_must_exist"
implementation:
  - backend/app/modules/budget/access.py
  - backend/app/modules/budget/tree/view.py
  - backend/app/modules/budget/tree/nodes.py
scope:
  - backend/app/modules/budget
---

# Gremium members see their cost centres

Without a budget permission, a person must see only the subtrees whose `view_gremium_id` is one
of their Gremien. A request that sets `viewGremiumId` to an id that is no Gremium must answer
422 `view_gremium_invalid`.

Reason: An id that names no Gremium gives the view to nobody, and the database refuses it
with an error that the person cannot read.

Test: The integration test sets the Gremium of the view to a Gremium and to an unknown id.

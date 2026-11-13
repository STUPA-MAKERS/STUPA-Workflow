---
id: "000844"
title: A Gremium with a budget is not deleted
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_gremium_with_a_budget_is_not_deleted"
  - "backend/tests/unit/modules/admin/test_delete_gremium_inuse_conflict.py:test_delete_gremium_with_a_budget_raises_conflict"
  - "frontend/src/app/pages/admin/committees/gremien.component.spec.ts:AdminGremienComponent"
implementation:
  - backend/app/modules/admin/service/gremien.py
  - frontend/src/app/pages/admin/committees/gremien.component.ts
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin/committees
---

# A Gremium with a budget is not deleted

The delete of a Gremium that a budget belongs to must answer 409 `gremium_has_budget` and
must change nothing. The page must tell the person to delete the budget first.

Reason: The database deletes the budgets of a Gremium with it, and with them the
Kostenstellen, the bookings and the Haushaltsplan. That way goes around the rules of the
budget delete (000254, 000820) and writes no audit entry for the money (000255, 000802).
The delete of the budget itself applies those rules.

Test: The integration test deletes a Gremium with a budget and reads the 409 and that the
budget and its plan stay, and deletes the Gremium after its budget. The page test reads the
text of the refusal.

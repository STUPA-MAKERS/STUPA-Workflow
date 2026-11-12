---
id: "000760"
title: A feature that needs another feature goes off with it
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/features/test_features_api.py:test_invoices_go_off_with_budget_and_return_to_their_state"
  - "backend/tests/unit/modules/site_config/test_features.py:test_invoices_are_off_while_budget_is_off_and_keep_their_switch"
  - "frontend/src/app/pages/admin/features/features.component.spec.ts:FeaturesComponent"
implementation:
  - backend/app/modules/site_config/features.py
  - frontend/src/app/pages/admin/features/features.component.ts
scope:
  - backend/app/modules
  - frontend/src/app
---

# A feature that needs another feature goes off with it

`Rechnungen` needs `Budget`. While `Budget` is off, `Rechnungen` must be off, and the switch of
`Rechnungen` must be locked and must show the text `Benötigt Budget`. When `Budget` goes on again,
`Rechnungen` must return to the state that the admin set before.

A feature that only shows records of another feature does not need it. `Kalender` stays on while
`Sitzungen` is off, and `Sitzungen` stays on while `Abstimmungen` is off.

Reason: An invoice books on a Kostenstelle, so the invoices cannot work without the budget. One
press must be enough to switch a feature off.

Test: `backend/tests/integration/modules/features/test_features_api.py` switches `Budget` off and
gets `feature_disabled` from an invoice route. It switches `Budget` on again and reads the stored
state of `Rechnungen`. `frontend/src/app/pages/admin/features/features.component.spec.ts` finds the
locked switch with the text `Benötigt Budget`.

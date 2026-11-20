---
id: "001681"
title: The server refuses a Kostenstelle outside the subtree
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/forms/validation.py
  - backend/app/modules/applications/service/form_checks.py
scope:
  - backend/app/modules/forms
  - backend/app/modules/budget
  - frontend/src/app/shared/formly
  - frontend/src/app/pages/admin/forms
---

# The server refuses a Kostenstelle outside the subtree

The backend must refuse an answer of a `budget_select` field with a root (001680) when the
Kostenstelle is not below the root in the fiscal year. The answer is 422
`cost_centre_outside_subtree`.

Reason: A check that only the picker makes can be passed by a direct API call.

Test: A backend integration test submits a Kostenstelle outside the root.

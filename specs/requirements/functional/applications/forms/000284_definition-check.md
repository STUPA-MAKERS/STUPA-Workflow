---
id: "000284"
title: A form definition is checked at save time
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/forms/validation.py
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# A form definition is checked at save time

The save of a form must refuse these errors:

- a duplicate key
- a promoted field that is not numeric (`number` or `currency`). A `computed` field with
  `promoteTarget: "amount"` is allowed (002840).
- a `computed` amount field beside a `positions` field, a `funding` field or another field
  with `promoteTarget: "amount"`, because the amount must have one source
- a JsonLogic operator outside the whitelist
- a pattern that does not compile or can backtrack without limit

Test: `backend/tests/unit/test_forms_validation.py` saves a form with a computed amount field
and refuses a computed amount field beside a `positions` field.

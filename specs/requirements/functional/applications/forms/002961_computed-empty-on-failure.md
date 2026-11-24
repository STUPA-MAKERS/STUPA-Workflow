---
id: "002961"
title: A computed field that cannot be computed stays empty
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/forms/validation.py
  - frontend/src/app/shared/forms/form-rules.ts
scope:
  - backend/app/modules/forms
  - frontend/src/app/shared/forms
---

# A computed field that cannot be computed stays empty

When the expression of a `computed` field that is not the amount cannot be evaluated, the field
must have no value. Examples are an empty operand and a division by 0. A result that is not a
finite number also gives no value. The server must not answer 422 for such a field, and the
form must not stop the submit. For the computed amount, 002841 applies.

Reason: An empty answer is a normal state of a form. A value that only shows information must
not stop an Antrag that is complete.

Test: `backend/tests/unit/modules/forms/test_computed_format.py`: an empty funding and costs of
0 € give no value for `foerderquote` and `eigenanteil`, and `validate_answers` raises no error.

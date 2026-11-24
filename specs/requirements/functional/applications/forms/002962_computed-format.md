---
id: "002962"
title: A computed field has a display format
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/shared/config_schemas.py
  - backend/app/modules/forms/validation.py
  - frontend/src/app/core/api/models.ts
  - frontend/src/app/shared/forms/form-rules.ts
scope:
  - backend/app/modules/forms
  - frontend/src/app/shared/forms
---

# A computed field has a display format

A `computed` field must have the setting `format`: `number` (the default), `money` or
`percent`. Another field type must not have `format`. The server must store a `money` value
rounded half up to cents and a `percent` value rounded half up to four decimal places. A
`percent` value is a fraction: 0.8333 is 83.33 %. The computed amount is always `money`.

Reason: A rate and an own share are not plain numbers, and a reader must see them as a percent
and as money. The server rounds, so that the stored value is the value that the reader sees.

Test: `backend/tests/unit/modules/forms/test_computed_format.py` stores 0.8333 for 1000 / 1200
with `percent` and 200.0 for 1200 - 1000.004 with `money`, and refuses `format` at a `text`
field.

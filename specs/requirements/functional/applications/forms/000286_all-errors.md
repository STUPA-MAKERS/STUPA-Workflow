---
id: "000286"
title: Answer validation reports all errors
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/forms/validation.py
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# Answer validation reports all errors

The answer check must collect the errors of all fields and must return them together. Computed
fields must be evaluated first, in field order.

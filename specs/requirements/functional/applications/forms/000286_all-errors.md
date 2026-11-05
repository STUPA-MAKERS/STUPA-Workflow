---
id: "000286"
title: Answer validation reports all errors
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# Answer validation reports all errors

The answer check collects the errors of all fields and returns them together. Computed fields
are evaluated first, in field order.

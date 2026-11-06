---
id: "000282"
title: Every form has a title field
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/forms/validation.py
  - backend/app/modules/applications/service/reads.py
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# Every form has a title field

The effective form must start with a required `title` field, unless the type defines a field
with the key `title`. The form builder must not be able to edit this field.

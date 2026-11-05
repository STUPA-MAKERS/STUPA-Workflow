---
id: "000282"
title: Every form has a title field
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# Every form has a title field

The effective form starts with a required `title` field, unless the type defines a field with
the key `title`. The form builder cannot edit this field.

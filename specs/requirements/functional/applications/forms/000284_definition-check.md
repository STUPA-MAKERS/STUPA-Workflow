---
id: "000284"
title: A form definition is checked at save time
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

# A form definition is checked at save time

The save of a form must refuse these errors:

- a duplicate key
- a promoted field that is not numeric
- a JsonLogic operator outside the whitelist
- a pattern that does not compile or can backtrack without limit

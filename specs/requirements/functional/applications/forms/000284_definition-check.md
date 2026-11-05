---
id: "000284"
title: A form definition is checked at save time
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# A form definition is checked at save time

The save of a form refuses these errors:

- a duplicate key
- a promoted field that is not numeric
- a JsonLogic operator outside the whitelist
- a pattern that does not compile or can backtrack without limit

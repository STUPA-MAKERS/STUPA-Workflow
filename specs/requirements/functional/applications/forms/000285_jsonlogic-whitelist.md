---
id: "000285"
title: JsonLogic uses a whitelist
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# JsonLogic uses a whitelist

`visibleIf` and `compute` must use only `== != > >= < <= and or not var + - * / in`. If a
`visibleIf` fails to evaluate, the field must count as visible and must be validated.

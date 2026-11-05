---
id: "000285"
title: JsonLogic uses a whitelist
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# JsonLogic uses a whitelist

`visibleIf` and `compute` use only `== != > >= < <= and or not var + - * / in`. If a
`visibleIf` fails to evaluate, the field counts as visible and is validated.

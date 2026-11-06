---
id: "000140"
title: The default fiscal year holds today
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree_rules.py
  - backend/app/modules/budget/tree/service_base.py
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# The default fiscal year holds today

The default fiscal year must be the active open year. If more than one exists, it must be the
active open year that holds the current date.

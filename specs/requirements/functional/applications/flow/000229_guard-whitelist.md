---
id: "000229"
title: Guards and actions come from a whitelist
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# Guards and actions come from a whitelist

A guard and an action must use only the operators and action types of the whitelist in
`app/shared/guards.py`. The server must not evaluate code from the configuration. An unknown
operator or action fails at save time, not at runtime.

Reason: The flow is admin input. Code from input is a security hole.

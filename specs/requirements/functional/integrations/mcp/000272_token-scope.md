---
id: "000272"
title: An agent token has a scope and a lifetime
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - mcp/
---

# An agent token has a scope and a lifetime

The user picks the scopes and a lifetime of 1 hour, 8 hours, 1 day, 30 days, 90 days or
never. A scope caps the global and the gremium permissions of the token, also for an admin.
The consent needs `mcp.use`.

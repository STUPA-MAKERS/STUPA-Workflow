---
id: "000272"
title: An agent token has a scope and a lifetime
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth
  - backend/app/deps.py
  - mcp/
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - mcp/
---

# An agent token has a scope and a lifetime

The user must pick the scopes and a lifetime of 1 hour, 8 hours, 1 day, 30 days, 90 days or
never. A scope must cap the global and the gremium permissions of the token, also for an admin.
The consent must need `mcp.use`.

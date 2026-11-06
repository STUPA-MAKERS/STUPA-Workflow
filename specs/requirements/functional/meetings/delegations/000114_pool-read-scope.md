---
id: "000114"
title: Pool substitutes read like members
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/pool.py
  - backend/app/modules/auth/rbac.py
scope:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - backend/app/modules/auth
---

# Pool substitutes read like members

A pool substitute must read the Anträge, Kostenstellen and calendar of the Gremium like a
member. A pool substitute must get no Gremium permissions.

---
id: "000461"
title: External delegates need a Gremium switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/service.py
scope:
  - backend/app/modules/delegations
  - backend/app/modules/admin/models.py
---

# External delegates need a Gremium switch

A delegate who is neither a member nor in the substitute pool must get 403, unless the Gremium
has `delegationAllowExternal`.

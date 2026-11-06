---
id: "000228"
title: A state is normal or a vote state
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/flow/vote_gremium.py
  - backend/app/shared/config_schemas.py
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# A state is normal or a vote state

A state has the kind `normal` or `vote`. A vote state names its Gremium in one of two ways:
a fixed `gremiumId`, or `gremiumSource: "budget"` for the deciding Gremium of the cost centre.
The initial state must not use `gremiumSource: "budget"`.

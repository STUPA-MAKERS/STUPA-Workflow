---
id: "000363"
title: A delegation moves the vote
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/service.py
  - backend/app/modules/voting/service.py
scope:
  - backend/app/modules/delegations
  - backend/app/modules/voting
---

# A delegation moves the vote

A delegation with voting must block the own ballot of the delegator. The delegate must cast one
more ballot for the delegator.

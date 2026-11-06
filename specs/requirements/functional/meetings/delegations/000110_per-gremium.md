---
id: "000110"
title: Vote delegation is a Gremium setting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - backend/app/modules/gremien
scope:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - backend/app/modules/gremien
---

# Vote delegation is a Gremium setting

Vote delegation must be on or off only per Gremium (`allowVoteDelegation`). It must not be a
setting of the instance, a person or a role.

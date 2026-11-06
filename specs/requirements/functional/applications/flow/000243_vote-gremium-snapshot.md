---
id: "000243"
title: The vote Gremium is a snapshot
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/flow/vote_gremium.py
  - backend/app/modules/flow/service.py
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/applications
  - backend/app/modules/voting
---

# The vote Gremium is a snapshot

Every state change must store the Gremium of the target vote state on the Antrag. Every reader
of "the Gremium of the vote" must read this snapshot, not the flow configuration. If a budget
vote state has no deciding Gremium, the transition must be hidden and a fire must give 409
`no_vote_gremium`.

---
id: "000243"
title: The vote Gremium is a snapshot
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/applications
  - backend/app/modules/voting
---

# The vote Gremium is a snapshot

Every state change stores the Gremium of the target vote state on the Antrag. Every reader of
"the Gremium of the vote" reads this snapshot, not the flow configuration. If a budget vote
state has no deciding Gremium, the transition is hidden and a fire gives 409 `no_vote_gremium`.

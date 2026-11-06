---
id: "000230"
title: Actor gates apply only to manual transitions
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# Actor gates apply only to manual transitions

`roleIs`, `isInCommittee`, `actorIsApplicant` and `isInVoteGremium` check the person who fires
a transition. An automatic transition must not use them. An automatic run sees no actor, so
such a gate cannot pass.

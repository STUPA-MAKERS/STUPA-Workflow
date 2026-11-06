---
id: "000364"
title: Only an eligible member delegates
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations
scope:
  - backend/app/modules/delegations
---

# Only an eligible member delegates

Only a member whose Gremium role holds `vote.cast` must be able to delegate. A global role or
an OIDC group must not count.

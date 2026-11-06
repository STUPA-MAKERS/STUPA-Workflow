---
id: "000364"
title: Only an eligible member delegates
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/delegations
---

# Only an eligible member delegates

Only a member whose Gremium role holds `vote.cast` can delegate. A global role or an OIDC group
does not count.

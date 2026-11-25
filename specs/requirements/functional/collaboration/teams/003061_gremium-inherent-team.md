---
id: "003061"
title: Every Gremium has exactly one inherent team
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/gremien
  - backend/migrations
---

# Every Gremium has exactly one inherent team

Every Gremium must have exactly one inherent team. The platform must create the team with the
Gremium and delete it with the Gremium. The name of the team must follow the name of the
Gremium. The members of the inherent team must be the active members of the Gremium at the time
of the read, so a membership change in OIDC changes the team at once. Nobody must add or remove
a member of an inherent team by hand, and nobody must delete an inherent team alone. A data
migration must create the inherent team of each existing Gremium.

Reason: Termine and boards point to a team, not to a Gremium. The Gremium stays the body for
meetings, votes and protocols.

Test: A backend test creates a Gremium and finds its team, renames the Gremium and reads the new
name, and refuses a member change and a delete of the team with 409.

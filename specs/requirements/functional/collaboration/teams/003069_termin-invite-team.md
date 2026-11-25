---
id: "003069"
title: A Termin invites teams and persons
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/calendar
  - backend/migrations
  - frontend/src/app/features/calendar
---

# A Termin invites teams and persons

A Termin must invite any number of teams and persons, never a Gremium. An invited team must
stand for the members of the team at the time of the read. The creator must be able to invite
only a team that the creator is a member of, or any team with `calendar.manage`. The data
migration must change each Gremium invitation into an invitation of the inherent team. This
replaces 000717.

Reason: A work group must be able to get Termine without being a Gremium.

Test: A backend test invites a team, adds a member to the team and reads the Termin as that
member.
